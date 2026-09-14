
from pathlib import Path
import shutil
import tempfile

from app.agent.pc_broker import AUTO, BLOCK, CONFIRM, PCCapabilityBroker

broker = PCCapabilityBroker()

status = broker.execute(broker.prepare("get_system_status", {}))
assert status.success, status.error

with tempfile.TemporaryDirectory(prefix="sara_broker_test_") as tmp:
    root = Path(tmp)
    folder = root / "Sara Test"

    created = broker.execute(
        broker.prepare("create_folder", {"path": str(folder)})
    )
    assert created.success and folder.is_dir(), created.error

    listed = broker.execute(
        broker.prepare("list_files", {"path": str(root)})
    )
    assert listed.success, listed.error

    delete_plan = broker.prepare(
        "delete_folder",
        {"path": str(folder)},
    )
    assert delete_plan.risk == CONFIRM

blocked = broker.prepare("run_shell", {"command": "whoami"})
assert blocked.risk == BLOCK

volume_plan = broker.prepare("set_volume", {"level": "35 percent"})
assert volume_plan.risk == AUTO
assert volume_plan.arguments["percent"] == 35

desktop_alias = broker.prepare("list_files_on_desktop", {})
assert desktop_alias.intent == "list_files"

print("PC BROKER V3 SMOKE TEST: PASS")
print("System status:", status.message)
print("Delete protection: PASS")
print("Sensitive shell block: PASS")
print("Intent alias normalization: PASS")
