from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent

MIN_LABELED_USES_PER_ACTION_TO_TRAIN = 50

MODEL_DIR = ROOT_DIR / "artifacts"
DEFAULT_MODEL_PATH = MODEL_DIR / "residual_action_mlp.pt"

ACTION_FAMILY_TO_INDEX = {
    "Weapon": 0,
    "Spell": 1,
    "MonAction": 2,
}
NUM_ACTION_NAME_BUCKETS = 1024

FEATURE_KEYS = [
    "base_weight",
    "expected_damage",
    "kill_chance",
    "impact_score",
    "damage_total",
    "extra_damage_total",
    "conditions_applied_count",
    "status_effects_applied_count",
    "targets_hit_count",
    "num_targets",
    "num_targets_selected",
    "num_targets_hit",
    "enemy_targets_hit",
    "ally_targets_hit",
    "self_targets_hit",
    "target_hp",
    "target_hp_pct",
    "target_ac",
    "target_save_bonus",
    "target_hp_mean",
    "target_hp_pct_min",
    "target_hp_pct_max",
    "target_ac_mean",
    "target_save_bonus_mean",
    "aoe_cells_covered",
    "aoe_is_lingering",
    "aoe_has_anchor",
    "aoe_shape_circle",
    "aoe_shape_cone",
    "aoe_shape_square",
    "aoe_shape_line",
    "actor_level",
    "actor_hp",
    "actor_hp_pct",
    "actor_ac",
    "actor_spell_mod",
    "actor_concentrating_before",
    "friendly_team_hp_pct",
    "enemy_team_hp_pct",
    "action_resource_before",
    "bonus_action_resource_before",
    "movement_resource_before",
    "action_resource_after",
    "bonus_action_resource_after",
    "movement_resource_after",
    "spell_slot_level_spent",
    "action_level",
    "action_range_ft",
    "action_cost_value",
    "is_healing",
    "is_aoe",
    "is_save",
    "is_to_hit",
    "has_linger",
    "ling_save_weight",
    "ling_effect_weight",
    "extra_effect_weight",
    "target_count_valid",
]

MAX_RESIDUAL_DELTA = 5.0
HIDDEN_DIMS = (128, 64)
BATCH_SIZE = 32
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 120
EARLY_STOPPING_PATIENCE = 15
