// AegisOS v6 — one-shot process launcher helper.
//
// Usage:  Exec { id: exec }  ...  exec.run(["google-chrome"])
//         exec.runShell("foot || alacritty || xterm")
//
// Each call spawns a fresh Quickshell Process (Quickshell.Io) and destroys
// it when the child exits, so the same helper can launch many apps.
import QtQuick
import Quickshell.Io

QtObject {
    id: root

    property Component procComponent: Component {
        Process {
        }
    }

    function run(command) {
        if (!command || command.length === 0)
            return;
        const proc = procComponent.createObject(root);
        proc.command = command;
        proc.running = true;
        proc.exited.connect(function () {
            proc.destroy();
        });
    }

    function runShell(script) {
        root.run(["sh", "-c", script]);
    }
}
