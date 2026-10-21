"""GET /api/v1/settings/restart-pending: restart-only settings saved since startup."""

from backend.app.services.app_settings import RESTART_SETTINGS

URL = "/api/v1/settings/"


def _start_with_saved_values(client) -> dict:
    """Pretend the backend started with the settings as saved now."""
    saved = client.get(URL).json()
    client.app.state.running_settings = {key: saved[key] for key in RESTART_SETTINGS}
    return saved


def test_nothing_pending_after_startup(test_client):
    _start_with_saved_values(test_client)
    assert test_client.get(f"{URL}restart-pending").json() == {"keys": []}


def test_a_saved_change_is_pending_until_changed_back(test_client):
    saved = _start_with_saved_values(test_client)
    workers = saved["max_concurrent_prepare"]

    test_client.patch(URL, json={"max_concurrent_prepare": workers + 1})
    assert test_client.get(f"{URL}restart-pending").json() == {"keys": ["max_concurrent_prepare"]}

    test_client.patch(URL, json={"max_concurrent_prepare": workers})
    assert test_client.get(f"{URL}restart-pending").json() == {"keys": []}


def test_settings_applied_live_are_never_pending(test_client):
    _start_with_saved_values(test_client)
    test_client.patch(URL, json={"grid_analysis_max_dim": 4096})
    assert test_client.get(f"{URL}restart-pending").json() == {"keys": []}
