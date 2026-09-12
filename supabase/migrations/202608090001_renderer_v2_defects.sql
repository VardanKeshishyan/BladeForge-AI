-- Make the v2 renderer's defect catalogue authoritative in persisted jobs, datasets,
-- and editable defect profiles. The initial MVP deliberately allowed LEE only.

alter table public.generation_jobs
  drop constraint if exists generation_jobs_defect_type_check;
alter table public.generation_jobs
  add constraint generation_jobs_defect_type_check check (defect_type in (
    'surface_crack', 'leading_edge_erosion', 'trailing_edge_damage', 'corrosion',
    'rust_staining', 'paint_peeling', 'coating_loss', 'scratches', 'dents',
    'lightning_strike', 'holes', 'chips', 'delamination', 'oil_stains',
    'dirt_buildup', 'ice_buildup', 'structural_deformation'
  ));

alter table public.datasets
  drop constraint if exists datasets_defect_type_check;
alter table public.datasets
  add constraint datasets_defect_type_check check (defect_type in (
    'multi', 'surface_crack', 'leading_edge_erosion', 'trailing_edge_damage',
    'corrosion', 'rust_staining', 'paint_peeling', 'coating_loss', 'scratches',
    'dents', 'lightning_strike', 'holes', 'chips', 'delamination', 'oil_stains',
    'dirt_buildup', 'ice_buildup', 'structural_deformation'
  ));

alter table public.defect_profiles
  drop constraint if exists defect_profiles_defect_type_check;
alter table public.defect_profiles
  add constraint defect_profiles_defect_type_check check (defect_type in (
    'surface_crack', 'leading_edge_erosion', 'trailing_edge_damage', 'corrosion',
    'rust_staining', 'paint_peeling', 'coating_loss', 'scratches', 'dents',
    'lightning_strike', 'holes', 'chips', 'delamination', 'oil_stains',
    'dirt_buildup', 'ice_buildup', 'structural_deformation'
  ));

alter index if exists public.one_system_lee_profile_idx
  rename to one_system_defect_profile_idx;
