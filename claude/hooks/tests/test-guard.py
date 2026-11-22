#!/usr/bin/env python3
"""Numbered proof of the protection-integrity guard. The exit code is the verdict.

Each case feeds the hook a real PreToolUse payload and asserts DENY (exit 2) or ALLOW
(exit 0). The ALLOW cases matter as much as the DENY ones: a guard that blocks ordinary
work gets switched off, and then it protects nothing.
"""
import json
import subprocess
import sys

import pathlib
# The guard sits one level up, next to the other hooks: resolve it from THIS file so the
# battery runs from a fresh clone, not only from the scratchpad it was written in.
GUARD = str((pathlib.Path(__file__).resolve().parent.parent / "guard-protection-integrity.sh"))
FLAG = "~/.claude-allow-secrets"

DENY, ALLOW = "DENY", "ALLOW"

CASES = [
    # --- the exact incident of 2026-11-22, and its near variants ---
    (DENY,  "Bash",  {"command": f"touch {FLAG}"},                          "le touch du drapeau (l'incident)"),
    (DENY,  "Bash",  {"command": "touch /Users/anisbessa/.claude-allow-secrets"}, "le meme en chemin absolu"),
    (DENY,  "Bash",  {"command": f"rm -f {FLAG}"},                          "supprimer le drapeau"),
    (DENY,  "Bash",  {"command": f"echo x > {FLAG}"},                       "creer le drapeau par redirection"),
    (DENY,  "Bash",  {"command": 'printf "" >> $HOME/.claude-allow-secrets'}, "creer le drapeau en ajout"),
    (DENY,  "Write", {"file_path": "/Users/anisbessa/.claude-allow-secrets", "content": ""},
                     "creer le drapeau avec Write (le trou: le hook n'ecoutait pas Write)"),
    (DENY,  "Bash",  {"command": "touch /etc/claude/allow-secrets"},        "creer le drapeau a l'emplacement root"),

    # --- neutralising the guard or its registration ---
    (DENY,  "Edit",  {"file_path": "/Users/anisbessa/.claude/settings.json",
                      "old_string": "a", "new_string": "b"},                "desenregistrer le hook via settings.json"),
    (DENY,  "Write", {"file_path": "/Users/anisbessa/.claude/hooks/block-secret-exposure.sh", "content": "exit 0"},
                     "reecrire le hook de secrets"),
    (DENY,  "Bash",  {"command": "sed -i '' 's/exit 2/exit 0/' ~/.claude/hooks/block-secret-exposure.sh"},
                     "neutraliser le hook par sed -i"),
    (DENY,  "Bash",  {"command": "chmod -x ~/.claude/hooks/block-secret-exposure.sh"},
                     "retirer le bit d'execution"),
    (DENY,  "Bash",  {"command": "mv ~/.claude/hooks/block-secret-exposure.sh /tmp/"},
                     "deplacer le hook hors de portee"),
    (DENY,  "Bash",  {"command": "cp /dev/null ~/.claude/hooks/guard-protection-integrity.sh"},
                     "vider le garde lui-meme"),
    (DENY,  "Bash",  {"command": "vim /Users/anisbessa/dev/workspace/talenteo/talenteo-brain/hooks/claude/block-secret-exposure.sh"},
                     "editer la source reelle du hook (la cible du lien)"),

    # --- privilege escalation is never the agent's to attempt ---
    (DENY,  "Bash",  {"command": "sudo mkdir -p /etc/claude"},              "sudo, meme pour installer la protection"),
    (DENY,  "Bash",  {"command": "ls -l && sudo chown root /etc/claude"},   "sudo cache en fin de chaine"),

    # --- ordinary work must keep passing ---
    (ALLOW, "Bash",  {"command": "cat ~/.claude/hooks/block-secret-exposure.sh"},
                     "LIRE le hook (diagnostiquer un refus doit rester possible)"),
    (ALLOW, "Bash",  {"command": "grep -n allow-secrets ~/.claude/hooks/block-secret-exposure.sh"},
                     "chercher dans le hook"),
    (ALLOW, "Bash",  {"command": "ls -la ~/.claude/hooks/"},                "lister les hooks"),
    (ALLOW, "Bash",  {"command": "mvn clean package -DskipTests"},          "un build"),
    (ALLOW, "Bash",  {"command": "git -C /tmp/x commit -m 'feat: x'"},      "un commit"),
    (ALLOW, "Write", {"file_path": "/Users/anisbessa/dev/workspace/hia/back-tenant/src/main/java/A.java", "content": "class A{}"},
                     "ecrire du code projet"),
    (ALLOW, "Bash",  {"command": "docker compose up -d"},                   "lancer le stack"),
    (ALLOW, "Bash",  {"command": "kubectl get pods -n hia-tenant"},         "lire le cluster"),
    (ALLOW, "Read",  {"file_path": "/Users/anisbessa/.claude/settings.json"},
                     "LIRE les settings (lecture seule, aucun outil d'ecriture)"),
]


def run(tool, tool_input):
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    done = subprocess.run(["bash", GUARD], input=payload, capture_output=True, text=True, timeout=20)
    return done.returncode, done.stderr


def main():
    failures = []
    for index, (expected, tool, tool_input, label) in enumerate(CASES, start=1):
        code, _ = run(tool, tool_input)
        actual = DENY if code == 2 else (ALLOW if code == 0 else f"EXIT{code}")
        ok = actual == expected
        print(f"{'OK ' if ok else 'KO '} {index:2d}. [{expected:5s}] {label}"
              + ("" if ok else f"  -> a repondu {actual}"))
        if not ok:
            failures.append(index)

    print(f"\n== {len(CASES) - len(failures)}/{len(CASES)} vert ==")
    if failures:
        print("cas en echec:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
