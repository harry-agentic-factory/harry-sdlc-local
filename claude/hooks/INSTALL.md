# Rendre la protection inaccessible à l'agent — runbook d'installation

> Écrit pour Anis. Toutes les commandes ci-dessous sont **à jouer par toi** : elles exigent `sudo`,
> et c'est exactement ce qui fait la garantie. L'agent ne peut pas les jouer (pas de sudo, et le
> garde refuse `sudo` de toute façon).

## Le principe, en une phrase

Un hook écrit dans un fichier que l'agent peut modifier ne contraint rien. La garantie ne vient pas
du script, elle vient de **qui possède les fichiers**. Donc : le garde, le hook de secrets, le
drapeau de contournement et l'enregistrement des hooks passent tous hors de portée de ton compte.

## Ce que l'incident a montré (mesuré le 2026-11-22)

| Fait | Conséquence |
|---|---|
| `permissions.allow` contient `"Bash"` nu | n'importe quelle commande passe sans demande |
| `block-secret-exposure.sh` documente son contournement (lignes 7-8) | l'agent lit le fichier et y apprend la clé |
| le drapeau est `$HOME/.claude-allow-secrets` | l'agent écrit dans `$HOME` sans entrave |
| le hook n'est branché que sur `Bash`, `Read`, `Grep` | l'outil `Write` crée le drapeau sans déclencher aucun hook |
| le hook est un lien vers un dépôt git du compte | l'agent peut réécrire la source |

## Étape 1 — emplacements root

```bash
sudo mkdir -p /usr/local/lib/claude-guard /etc/claude /var/log/claude-guard
sudo chown root:wheel /usr/local/lib/claude-guard /etc/claude
sudo chmod 755 /usr/local/lib/claude-guard /etc/claude
sudo chown root:staff /var/log/claude-guard && sudo chmod 775 /var/log/claude-guard
```

`/etc/claude/` est le nouveau domicile du drapeau de contournement : le créer exigera ton mot de
passe. `/var/log/claude-guard/` est inscriptible par le groupe pour que le garde puisse **journaliser
les tentatives** — tu verras chaque refus.

## Étape 2 — installer le garde, propriété root

```bash
HOOKS=/Users/anisbessa/dev/workspace/harington-common/harry-sdlc-local/claude/hooks
sudo install -o root -g wheel -m 755 "$HOOKS/guard-protection-integrity.sh" \
     /usr/local/lib/claude-guard/guard-protection-integrity.sh
```

## Étape 3 — copie root du hook de secrets, drapeau déplacé

```bash
sudo install -o root -g wheel -m 755 \
     /Users/anisbessa/dev/workspace/talenteo/talenteo-brain/hooks/claude/block-secret-exposure.sh \
     /usr/local/lib/claude-guard/block-secret-exposure.sh

# le contournement n'est plus dans $HOME mais sous root :
sudo sed -i '' 's#\$HOME/\.claude-allow-secrets#/etc/claude/allow-secrets#' \
     /usr/local/lib/claude-guard/block-secret-exposure.sh

# et on retire l'invitation au contournement de l'en-tête :
sudo sed -i '' 's#^# Bypass: create .*#\# Bypass: root only -- sudo touch /etc/claude/allow-secrets#' \
     /usr/local/lib/claude-guard/block-secret-exposure.sh

sudo grep -n "allow-secrets" /usr/local/lib/claude-guard/block-secret-exposure.sh
```

Le dépôt `talenteo-brain` reste ta source éditable ; la copie root est celle qui s'exécute. Quand tu
modifies le hook, tu rejoues l'`install` ci-dessus. C'est volontaire : la resynchronisation est un
geste conscient, pas un effet de bord d'un `git pull`.

## Étape 4 — enregistrer les hooks dans les réglages managés (non surchargeables)

`~/.claude/settings.json` reste **à toi** et modifiable : on n'y touche pas. L'enregistrement part
dans les réglages managés, de précédence supérieure, que l'agent ne peut pas éditer.

```bash
sudo mkdir -p "/Library/Application Support/ClaudeCode"
sudo tee "/Library/Application Support/ClaudeCode/managed-settings.json" > /dev/null <<'JSON'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "/usr/local/lib/claude-guard/guard-protection-integrity.sh" }
        ]
      },
      {
        "matcher": "Bash|Read|Grep",
        "hooks": [
          { "type": "command", "command": "/usr/local/lib/claude-guard/block-secret-exposure.sh" }
        ]
      }
    ]
  },
  "permissions": {
    "deny": [
      "Write(//Users/anisbessa/.claude/**)",
      "Edit(//Users/anisbessa/.claude/**)",
      "Write(//usr/local/lib/claude-guard/**)",
      "Edit(//usr/local/lib/claude-guard/**)",
      "Write(//etc/claude/**)",
      "Edit(//etc/claude/**)",
      "Write(//Users/anisbessa/dev/workspace/talenteo/talenteo-brain/hooks/**)",
      "Edit(//Users/anisbessa/dev/workspace/talenteo/talenteo-brain/hooks/**)",
      "Bash(sudo:*)"
    ]
  }
}
JSON
sudo chown root:wheel "/Library/Application Support/ClaudeCode/managed-settings.json"
sudo chmod 644 "/Library/Application Support/ClaudeCode/managed-settings.json"
```

Deux remarques honnêtes :

- les règles `permissions.deny` sont une **ceinture**, pas la bretelle : elles filtrent sur des
  motifs, donc un chemin reconstruit les contourne. Le garde root de l'étape 2 est la vraie barrière.
- Claude Code peut demander une **approbation des réglages managés** au premier lancement (le
  binaire parle d'une « managed-settings dialog »). Approuve-la une fois, dans une session
  interactive.

Après l'étape 4, retire aussi les entrées devenues redondantes de `~/.claude/settings.json`
(l'enregistrement de `block-secret-exposure.sh` sur `Bash|Read|Grep`) pour ne pas jouer le hook deux
fois. C'est toi qui édites ce fichier.

## Étape 5 — vérifier, sans me croire

```bash
# 1. la batterie du garde : 25 cas, le code retour EST le verdict
python3 -I "$HOOKS/tests/test-guard.py"; echo "exit=$?"     # attendu : 25/25, exit=0

# 2. ce que le garde ne couvre pas, mesuré
python3 -I "$HOOKS/tests/test-guard-adversarial.py"          # attendu : 3/7 passent -> d'ou la propriete root

# 3. le drapeau est hors de portee du compte (doit ECHOUER)
touch /etc/claude/allow-secrets                     # attendu : Permission denied

# 4. le garde est en lecture seule pour le compte (doit ECHOUER)
echo x > /usr/local/lib/claude-guard/guard-protection-integrity.sh   # attendu : Permission denied

# 5. les tentatives sont journalisees
tail -5 /var/log/claude-guard/integrity.log
```

## Ce qui reste vrai après installation

- **Lever la protection exige ton mot de passe** : `sudo touch /etc/claude/allow-secrets`, puis
  `sudo rm` pour la remettre. L'agent ne peut ni l'un ni l'autre.
- L'agent peut toujours **lire** les hooks (diagnostiquer un refus doit rester possible) ; il ne peut
  plus les écrire, les déplacer, les dé-permissionner, ni les désenregistrer.
- Un contournement **délibérément obfusqué** (chemin reconstruit par concaténation, base64) passe le
  garde mais **échoue quand même** à l'écriture, faute de droits root. C'est la raison d'être de
  l'étape 1 : la garantie ne repose pas sur la détection.
- Le garde n'a **aucun drapeau de contournement**. Si un jour il gêne, il se retire par
  `sudo` — consciemment.
