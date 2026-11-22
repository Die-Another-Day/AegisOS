// AegisOS v6 — PAM authentication context for the lock screen.
//
// This is a verbatim adaptation of the official Quickshell 0.3 lockscreen
// example (quickshell-examples, lockscreen/LockContext.qml):
//   - import Quickshell.Services.Pam
//   - PamContext with configDirectory + config, onPamMessage responds with
//     the typed password, onCompleted checks PamResult.Success.
// See README.md for sources.
//
// Security notes:
//   - Real PAM only. There is NO test-mode bypass, NO sudo-based check and
//     NO hardcoded password anywhere in this shell.
//   - The password is held only in `currentText` while the user types it,
//     handed to PAM on the prompt, and cleared on every completion.
//   - `user` is the locked account ("analyst"). `config` is the custom
//     password-only stack in pam/password.conf next to this config, so the
//     system /etc/pam.d/login stack is never disturbed.
import QtQuick
import Quickshell
import Quickshell.Services.Pam

Scope {
    id: root

    signal unlocked()
    signal failed()

    // Shared by every lock surface (one per screen) so all of them show
    // the same text and the same failure state.
    property string currentText: ""
    property bool unlockInProgress: false
    property bool showFailure: false

    // Clear the failure text once the user starts typing again.
    onCurrentTextChanged: showFailure = false

    function tryUnlock() {
        if (currentText === "")
            return;
        root.unlockInProgress = true;
        pam.start();
    }

    PamContext {
        id: pam

        user: "analyst"
        configDirectory: "pam"
        config: "password.conf"

        // pam_unix asks for a response to the password prompt.
        onPamMessage: {
            if (this.responseRequired) {
                this.respond(root.currentText);
            }
        }

        onCompleted: result => {
            root.currentText = "";
            if (result == PamResult.Success) {
                root.unlocked();
            } else {
                root.showFailure = true;
                root.failed();
            }
            root.unlockInProgress = false;
        }
    }
}
