import hashlib
import json
import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal
from app.api.errors import ApiError
from app.core.config import Settings
from app.db.models import Dataset, GenerationJob, JobStatus
from app.storage.supabase import StorageError, SupabaseStorage


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_dataset_file(relative_path: Path) -> str:
    if relative_path.as_posix() == "manifest.json":
        return "manifest"
    if relative_path.name.lower() == "readme.md":
        return "readme"
    top_level = relative_path.parts[0]
    if top_level == "images":
        return "image"
    if top_level == "masks":
        return "mask"
    if top_level == "annotations":
        return "annotation"
    if top_level == "metadata":
        return "metadata"
    raise ApiError(422, "invalid_dataset_package", "Dataset contains an unexpected file.")


def validate_package(directory: Path, job: GenerationJob) -> dict[str, object]:
    manifest_path = directory / "manifest.json"
    archive_path = directory / f"{job.dataset_name}.zip"
    if not manifest_path.is_file() or not archive_path.is_file():
        raise ApiError(422, "invalid_dataset_package", "Manifest or dataset archive is missing.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(422, "invalid_dataset_manifest", "Dataset manifest is invalid.") from exc
    samples = manifest.get("samples")
    if not isinstance(samples, list) or len(samples) != job.image_count:
        raise ApiError(422, "invalid_dataset_package", "Manifest sample count does not match the job.")
    for sample in samples:
        if not isinstance(sample, dict):
            raise ApiError(422, "invalid_dataset_package", "Manifest contains an invalid sample.")
        for key in ("image", "mask", "metadata"):
            relative = sample.get(key)
            if not isinstance(relative, str) or not (directory / relative).is_file():
                raise ApiError(422, "invalid_dataset_package", f"Required {key} file is missing.")
    is_v2 = manifest.get("renderer") == "bladeforge_cycles_v2" or manifest.get("schema_version") == "2.0"
    expected_defects = {str(job.defect_type)}
    config = job.config if isinstance(job.config, dict) else {}
    for layer in config.get("defect_layers") or []:
        if isinstance(layer, dict) and layer.get("defect_id"):
            expected_defects.add(str(layer["defect_id"]))
    if is_v2:
        delivered = {str(value) for value in (manifest.get("defect_types") or [])}
        if not expected_defects.issubset(delivered):
            raise ApiError(
                422,
                "invalid_dataset_package",
                "The v2 manifest does not contain every requested defect class.",
            )
        manifest_instance_defects: set[str] = set()
        for sample in samples:
            instance_mask = sample.get("instance_mask")
            instances = sample.get("instances")
            if not isinstance(instance_mask, str) or not (directory / instance_mask).is_file():
                raise ApiError(422, "invalid_dataset_package", "Required instance mask is missing.")
            if not isinstance(instances, list):
                raise ApiError(422, "invalid_dataset_package", "Instance annotations are missing.")
            for instance in instances:
                if (
                    not isinstance(instance, dict)
                    or int(instance.get("area") or 0) <= 0
                    or not isinstance(instance.get("segmentation"), dict)
                ):
                    raise ApiError(
                        422, "invalid_dataset_package", "Manifest contains an empty instance."
                    )
                manifest_instance_defects.add(str(instance.get("defect_id") or ""))
            try:
                json.loads((directory / str(sample["metadata"])).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ApiError(422, "invalid_dataset_package", "Sample metadata is invalid.") from exc
        if not expected_defects.issubset(manifest_instance_defects):
            raise ApiError(
                422,
                "invalid_dataset_package",
                "Rendered masks do not contain every requested defect class.",
            )
    annotation = (
        directory / "annotations" / "coco.json"
        if job.annotation_format == "coco_json"
        else directory / "annotations" / "data.yaml"
    )
    if not annotation.is_file():
        raise ApiError(422, "invalid_dataset_package", "Requested annotations are missing.")
    if is_v2 and job.annotation_format == "coco_json":
        try:
            coco = json.loads(annotation.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ApiError(422, "invalid_dataset_package", "COCO annotations are invalid.") from exc
        images_by_id = {
            int(image["id"]): image
            for image in coco.get("images") or []
            if isinstance(image, dict) and "id" in image
        }
        categories = {
            int(category["id"]): str(category["name"])
            for category in coco.get("categories") or []
            if isinstance(category, dict) and "id" in category and "name" in category
        }
        annotated_defects: set[str] = set()
        for record in coco.get("annotations") or []:
            if not isinstance(record, dict) or int(record.get("area") or 0) <= 0:
                raise ApiError(422, "invalid_dataset_package", "COCO contains an empty instance.")
            image = images_by_id.get(int(record.get("image_id") or 0))
            defect_id = categories.get(int(record.get("category_id") or 0))
            segmentation = record.get("segmentation")
            if image is None or defect_id is None or not isinstance(segmentation, dict):
                raise ApiError(422, "invalid_dataset_package", "COCO instance linkage is invalid.")
            size = segmentation.get("size")
            counts = segmentation.get("counts")
            if (
                size != [int(image["height"]), int(image["width"])]
                or not isinstance(counts, list)
                or sum(int(value) for value in counts) != int(image["height"]) * int(image["width"])
            ):
                raise ApiError(422, "invalid_dataset_package", "COCO segmentation RLE is invalid.")
            annotated_defects.add(defect_id)
        if not expected_defects.issubset(annotated_defects):
            raise ApiError(
                422,
                "invalid_dataset_package",
                "The annotations do not contain every requested defect class.",
            )
    return manifest


class DatasetService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.storage = SupabaseStorage(settings)

    async def get(self, principal: Principal, dataset_id: uuid.UUID) -> Dataset:
        dataset = await self.session.scalar(
            select(Dataset).where(
                Dataset.id == dataset_id,
                Dataset.organization_id == principal.organization_id,
            )
        )
        if dataset is None:
            raise ApiError(404, "dataset_not_found", "Dataset not found.")
        return dataset

    async def list(self, principal: Principal, page: int, page_size: int) -> dict[str, object]:
        total = int(
            (
                await self.session.execute(
                    text("select count(*) from datasets where organization_id = :org_id"),
                    {"org_id": principal.organization_id},
                )
            ).scalar_one()
        )
        rows = (
            await self.session.execute(
                text(
                    """
                    select id, job_id, name, defect_type, image_count, annotation_formats,
                           file_size_bytes, status, preview_storage_path, created_at, updated_at
                    from datasets
                    where organization_id = :org_id
                    order by created_at desc
                    offset :offset limit :limit
                    """
                ),
                {
                    "org_id": principal.organization_id,
                    "offset": (page - 1) * page_size,
                    "limit": page_size,
                },
            )
        ).mappings()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        }

    async def detail(self, principal: Principal, dataset_id: uuid.UUID) -> dict[str, object]:
        dataset = await self.get(principal, dataset_id)
        rows = (
            await self.session.execute(
                text(
                    """
                    select id, file_name, file_type, content_type, file_size_bytes,
                           checksum_sha256, created_at
                    from dataset_files
                    where dataset_id = :dataset_id and organization_id = :org_id
                    order by created_at
                    """
                ),
                {"dataset_id": dataset_id, "org_id": principal.organization_id},
            )
        ).mappings()
        return {
            "dataset": {
                "id": dataset.id,
                "job_id": dataset.job_id,
                "name": dataset.name,
                "defect_type": dataset.defect_type,
                "image_count": dataset.image_count,
                "annotation_formats": dataset.annotation_formats,
                "file_size_bytes": dataset.file_size_bytes,
                "status": dataset.status,
                "created_at": dataset.created_at,
                "updated_at": dataset.updated_at,
            },
            "files": [dict(row) for row in rows],
        }

    async def signed_archive(self, principal: Principal, dataset_id: uuid.UUID) -> str:
        dataset = await self.get(principal, dataset_id)
        if dataset.status != "available" or not dataset.archive_storage_path:
            raise ApiError(409, "dataset_not_available", "The validated archive is not available.")
        try:
            url = await self.storage.signed_url(
                self.settings.dataset_bucket, dataset.archive_storage_path
            )
        except StorageError as exc:
            raise ApiError(502, "storage_unavailable", "Could not create a download link.") from exc
        self.session.add(
            __import__("app.db.models", fromlist=["UsageEvent"]).UsageEvent(
                id=uuid.uuid4(),
                organization_id=principal.organization_id,
                job_id=dataset.job_id,
                event_type="dataset_download",
                image_count=0,
                gpu_seconds=0,
                storage_bytes=0,
                metadata_={"dataset_id": str(dataset.id)},
                recorded_at=datetime.now(UTC),
            )
        )
        await self.session.commit()
        return url

    async def signed_file(
        self, principal: Principal, dataset_id: uuid.UUID, file_id: uuid.UUID
    ) -> str:
        await self.get(principal, dataset_id)
        row = (
            await self.session.execute(
                text(
                    """
                    select storage_path from dataset_files
                    where id = :file_id and dataset_id = :dataset_id and organization_id = :org_id
                    """
                ),
                {"file_id": file_id, "dataset_id": dataset_id, "org_id": principal.organization_id},
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "dataset_file_not_found", "Dataset file not found.")
        try:
            return await self.storage.signed_url(self.settings.dataset_bucket, row["storage_path"])
        except StorageError as exc:
            raise ApiError(502, "storage_unavailable", "Could not create a download link.") from exc

    async def finalize_local_package(
        self, job: GenerationJob, directory: Path, gpu_seconds: float
    ) -> Dataset:
        manifest = validate_package(directory, job)
        archive = directory / f"{job.dataset_name}.zip"
        preview_candidates = sorted((directory / "images").glob("*"))
        preview = preview_candidates[0] if preview_candidates else None
        dataset_id = uuid.uuid4()
        prefix = f"{job.organization_id}/{dataset_id}"
        archive_object = f"{prefix}/{archive.name}"
        manifest_object = f"{prefix}/manifest.json"
        uploads: list[tuple[Path, str, str, str]] = [
            (archive, archive_object, "archive", "application/zip"),
        ]
        preview_object: str | None = None
        for local_path in sorted(directory.rglob("*")):
            if not local_path.is_file() or local_path == archive:
                continue
            relative_path = local_path.relative_to(directory)
            object_path = f"{prefix}/{relative_path.as_posix()}"
            uploads.append(
                (
                    local_path,
                    object_path,
                    classify_dataset_file(relative_path),
                    mimetypes.guess_type(local_path.name)[0] or "application/octet-stream",
                )
            )
            if preview is not None and local_path == preview:
                preview_object = object_path
        uploaded: list[str] = []
        try:
            for local_path, object_path, _, content_type in uploads:
                await self.storage.upload(
                    self.settings.dataset_bucket, object_path, local_path, content_type
                )
                uploaded.append(object_path)
            async with self.session.begin():
                delivered_defect_type = str(manifest.get("defect_type") or job.defect_type)
                dataset = Dataset(
                    id=dataset_id,
                    organization_id=job.organization_id,
                    job_id=job.id,
                    created_by=job.created_by,
                    name=job.dataset_name,
                    defect_type=delivered_defect_type,
                    image_count=job.image_count,
                    annotation_formats=[job.annotation_format],
                    file_size_bytes=archive.stat().st_size,
                    archive_storage_path=archive_object,
                    manifest_storage_path=manifest_object,
                    preview_storage_path=preview_object,
                    status="available",
                    validated_at=datetime.now(UTC),
                )
                self.session.add(dataset)
                await self.session.flush()
                for local_path, object_path, file_type, content_type in uploads:
                    await self.session.execute(
                        text(
                            """
                            insert into dataset_files (
                              id, dataset_id, organization_id, file_name, file_type, storage_path,
                              content_type, file_size_bytes, checksum_sha256
                            ) values (
                              :id, :dataset_id, :org_id, :file_name, :file_type, :storage_path,
                              :content_type, :file_size, :checksum
                            )
                            """
                        ),
                        {
                            "id": uuid.uuid4(),
                            "dataset_id": dataset_id,
                            "org_id": job.organization_id,
                            "file_name": (
                                local_path.name
                                if file_type == "archive"
                                else local_path.relative_to(directory).as_posix()
                            ),
                            "file_type": file_type,
                            "storage_path": object_path,
                            "content_type": content_type,
                            "file_size": local_path.stat().st_size,
                            "checksum": sha256_file(local_path),
                        },
                    )
                job.status = JobStatus.complete
                job.current_stage = "complete"
                job.progress = 100
                job.completed_at = datetime.now(UTC)
                await self.session.execute(
                    text(
                        """
                        insert into job_events (job_id, organization_id, event_type, message, metadata)
                        values (
                          :job_id, :org_id, 'complete', 'Dataset validated and stored.',
                          cast(:metadata as jsonb)
                        )
                        """
                    ),
                    {
                        "job_id": job.id,
                        "org_id": job.organization_id,
                        "metadata": json.dumps({"dataset_id": str(dataset_id)}),
                    },
                )
                await self.session.execute(
                    text(
                        """
                        insert into usage_events (
                          organization_id, job_id, event_type, image_count, gpu_seconds,
                          storage_bytes, metadata
                        ) values (
                          :org_id, :job_id, 'images_generated', :image_count, 0,
                          :storage_bytes, '{}'::jsonb
                        )
                        """
                    ),
                    {
                        "org_id": job.organization_id,
                        "job_id": job.id,
                        "image_count": job.image_count,
                        "storage_bytes": archive.stat().st_size,
                    },
                )
                await self.session.execute(
                    text(
                        """
                        insert into usage_events (
                          organization_id, job_id, event_type, gpu_seconds, metadata
                        ) values (
                          :org_id, :job_id, 'gpu_success', :gpu_seconds, '{}'::jsonb
                        )
                        """
                    ),
                    {
                        "org_id": job.organization_id,
                        "job_id": job.id,
                        "gpu_seconds": gpu_seconds,
                    },
                )
            return dataset
        except Exception:
            await self.session.rollback()
            try:
                await self.storage.remove(self.settings.dataset_bucket, uploaded)
            except StorageError:
                pass
            raise
