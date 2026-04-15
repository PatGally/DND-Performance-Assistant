from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent

MIN_LABELED_USES_PER_ACTION_TO_TRAIN = 10

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
    "target_hp",
    "target_hp_pct",
    "target_ac",
    "target_save_bonus",
    "actor_level",
    "actor_hp",
    "actor_hp_pct",
    "actor_ac",
    "actor_spell_mod",
    "num_targets",
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
