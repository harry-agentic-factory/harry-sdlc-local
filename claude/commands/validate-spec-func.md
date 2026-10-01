Gate FONCTIONNELLE d'une story ou d'un épic — revue agent, verdict humain, consignation : $ARGUMENTS

Tu es Harry. **Profil : bascule en `BA`** — sans l'annoncer (« Écrire pour un humain »). Résous le projet (`sdlc projects`, si ambigu demande) ;
toutes les commandes sont `sdlc --project <PREFIX> …`. Cible = `<STORY>` ou `<EPIC>` (de préférence l'**épic** :
une erreur fonctionnelle entre deux stories ne se voit qu'en lisant tout le lot).

> **L'agent recommande, l'humain décide.** Cette gate passe `spec_func → spec_func_validated` et la CLI la
> **refuse** tant qu'il n'existe pas de verdict **signé par un humain**. Tu ne signes jamais, même en mode auto.

## Déroulé

1. **État** : `sdlc get <STORY>` ou `sdlc status <EPIC>` — les stories visées doivent être en `spec_func`.
2. **Revue agent** : lance `harry-archi` en **mode document de revue** (cf. son prompt) sur le PRD, le `refine.md`
   et le(s) `spec-func.md` visés, code et Brain à l'appui. Il écrit :
   - épic : `<EPIC>/review-spec-func.md` ; story : `<EPIC>/stories/<STORY>/review-spec-func.md`.
   Constats numérotés `B`/`M`/`m`/`S`, preuve, recommandation, consensus. Revue déjà présente et specs corrigées
   depuis ⇒ demande une **revue ciblée** (nouvelle version de la même revue), jamais un nouveau fichier.
3. **Traitement humain** : `/process-review <chemin de la revue>` — l'humain décide point par point, le verdict
   `review-spec-func-verdict.md` (à côté de la revue) avance en `draft` puis est **signé par l'humain**.
4. **Consignation** (seulement quand le verdict est `status: signed`) :
   ```bash
   sdlc --project <PREFIX> validate-spec-func <STORY|EPIC> --verdict <…>/review-spec-func-verdict.md
   ```
   La CLI vérifie le verdict (signé, signataire humain, tous les constats décidés, bonne gate, bonne cible), puis
   écrit le journal (`revue@empreinte`, `verdict@empreinte`, signataire), les liens `review_spec_func` /
   `review_spec_func_verdict`, un item de dette `pm` par réserve ou contournement, et fait la transition.
   Issue `returned` ⇒ pas de transition : corrige les specs puis revue ciblée, et on repasse.

Ancien nom accepté : `sdlc validate-func` (alias, même comportement — `--verdict` compris).

## Sortie
Dis à l'humain (règle « Écrire pour un humain » de la persona : en phrases, documents nommés par leur titre, comptes en toutes lettres, sans chemin, sans commande, sans flèche, 5 lignes au plus) : l'issue de la gate fonctionnelle, les stories qui avancent, la dette créée s'il y en a.
**Puis** propose de passer à la spec technique.
