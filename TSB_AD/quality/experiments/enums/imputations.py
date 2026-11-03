"""Settings of the PyPOTS imputers (`cleaning.py`)."""

WINDOW = 96  # points per sample (`n_steps`) of the learned imputers
EPOCHS = 20  # training epochs of the learned imputers (PyPOTS' default 100 costs 5x the time for a similar RMSE)
# The parameters PyPOTS requires without a default (values of PyPOTS' README example); the rest keep their defaults.
REQUIRED_PARAMS = {
    "saits": {"n_layers": 2, "d_model": 256, "n_heads": 4, "d_k": 64, "d_v": 64, "d_ffn": 128},
}
