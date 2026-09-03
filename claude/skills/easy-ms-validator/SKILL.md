---
name: easy-ms-validator
description: Pattern de validation fluide EasyMS (`com.easyms.rest.ms.rest.Validator`) utilisé dans les microservices Java/Spring bâtis sur le socle EasyMS. Explique l'API (of/validate/validateIf/execute + extraction Function + validation CONDITIONNELLE doNothing/ifMatch), la sémantique exacte (assert-vrai vs throw-si-vrai), comment écrire une validation ADAPTÉE À UN MODE, et l'intégration avec le RestExceptionHandler EasyMS. À charger dès qu'on écrit/relit une validation d'entrée dans un `*Resource`/`*Service` d'un repo qui utilise EasyMS.
---

# Pattern de validation EasyMS — `Validator`

`com.easyms.rest.ms.rest.Validator<T>` (jar `easyms-rest-starter`) = builder fluide de validation. On enchaîne
des assertions sur un objet, puis `execute()` **lève** si au moins une a échoué. C'est le mécanisme de validation
d'entrée du socle : **réutilise-le, n'invente pas un mécanisme parallèle** dans un `ValidationService` maison.

## API (décodée du bytecode)
```
Validator.of(T object)                                             // point d'entrée
  .validate(Predicate<T> p, String|Supplier<X extends Throwable>)  // ASSERTE p==true ; sinon collecte l'exception
  .validateIf(Predicate<T> p, String|Supplier<X>)                  // SI p==true -> collecte l'exception
  .validate(Function<T,U> f, Predicate<U> p, String|Supplier<X>)   // extrait U=f(T) puis asserte p(U)
  .validateIf(Function<T,U> f, Predicate<U> p, String|Supplier<X>) // extrait puis throw-si-vrai
  .validateWithExceptions(Predicate<T>, Supplier<List<X>>)         // idem, plusieurs exceptions
  .validateIfWithExceptions(...)                                   //
  .ifMatch(U u, Predicate<U> p)                                    // validation CONDITIONNELLE (voir plus bas)
  .doNothing() / .resetDoNothing()                                 // désactive/réactive les validations suivantes
  .execute()                                                       // LÈVE si des exceptions ont été collectées
  .get() / .isSuccess() / .isFailure() / .ifValid()               // accès résultat sans lever
Validator.throwException(Throwable)                                // utilitaire de throw
```

## Sémantique — LE point à ne pas confondre
- **`validate(p, ex)`** = « **p DOIT être vrai** ». Si `p(obj)==false` → exception. (ex. `validate(Optional::isPresent, …)`.)
- **`validateIf(p, ex)`** = « **si p est vrai, c'est une erreur** ». Si `p(obj)==true` → exception. (ex. `validateIf(CollectionUtils::isEmpty, …)` = interdit vide.)
- **`execute()`** lève — typiquement une `IllegalStateException` qui *porte les exceptions collectées en suppressed*.
  Le **RestExceptionHandler EasyMS** mappe ensuite l'exception métier (ex. `UnprocessedEntityException` → HTTP
  422/400, `ResourceAccessException` → 404) vers le format `ApiError`. **Ne construis pas de `ResponseEntity`
  d'erreur à la main.** Sans `execute()`, **rien n'est levé** (piège classique : oublier `.execute()`).

## Exception & message
Passe soit une **`String`** (clé d'erreur i18n, ex. `HiaMessage.hia_convention_family_required.getErrorKey()`),
soit un **`Supplier<X>`** d'exception métier (`() -> new UnprocessedEntityException("…")`,
`() -> new ResourceAccessException(HiaMessage.x.getErrorKey())`). Préfère la **clé i18n** quand elle existe.

## Validation ADAPTÉE À UN MODE
Quand la contrainte dépend d'un « mode » (champ optionnel présent/absent, type de requête…), deux voies :
1. **Branche explicite** (la plus lisible) : `if (mode == DEFAULT) return;` puis `Validator.of(...).validateIf(...).execute()`
   pour le mode explicite. Exemple, sur une requête qui accepte un mode implicite et un mode explicite :
   ```java
   public void validateEnrollmentFamilySelection(ConventionFamilySelection sel) {
       if (sel == null) return;                       // mode DEFAULT : famille résolue serveur, aucune contrainte d'entrée
       Validator.of(sel)                              // mode EXPLICIT : all XOR familyIds
           .validateIf(s -> isTrue(s.getAll()) && isNotEmpty(s.getFamilyIds()), () -> new UnprocessedEntityException("all/familyIds exclusifs"))
           .validateIf(s -> !isTrue(s.getAll()) && isEmpty(s.getFamilyIds()),   () -> new UnprocessedEntityException("renseigner all OU familyIds"))
           .execute();
   }
   ```
2. **Conditionnel fluide** : `doNothing()` (désactive les validations suivantes) puis `ifMatch(u, p)` /
   `resetDoNothing()` pour ne les réactiver que si le mode matche. Plus dense, moins lisible — préfère la branche
   explicite sauf chaîne longue.

> ⚠️ **Ne valide pas trop tôt** : une validation d'entrée qui exige un champ que le **defaulting serveur**
> remplira plus tard **court-circuite** le defaulting. *Cas vécu* : une validation au contrôleur exigeait en dur
> une valeur de liste que le serveur savait déduire des settings → le defaulting ne s'appliquait jamais. **Valide selon
> le mode**, et laisse le **garde-fou aval** (sur la valeur RÉSOLUE) rejeter le cas vraiment invalide.

## Où valider quoi
- **Contrôleur (`*Resource`)** : validation d'ENTRÉE légère + mode (présence/cohérence des champs, périmètre, existence).
- **Service** : règles métier + **cohérence dépendante de la DB** (ex. « la famille appartient au niveau/au client »)
  et validation de la **valeur résolue** (post-defaulting). Ne duplique pas inutilement entre les deux couches.

## Pièges
- Oublier **`.execute()`** → aucune validation n'est effective.
- Confondre `validate` (assert vrai) et `validateIf` (throw si vrai).
- Valider la requête **brute** avant le defaulting (cf. ⚠️ ci-dessus).
- Recréer un format d'erreur au lieu de laisser le **RestExceptionHandler/ApiError** EasyMS mapper l'exception.

## Vérifier l'API dans le repo courant
`Validator` est dans `easyms-rest-starter` (versions multiples en `.m2`). Décompile pour confirmer la signature
exacte : `javap -p` sur `com/easyms/rest/ms/rest/Validator.class` extrait du jar. Les `ValidationService.*` du
repo sont les meilleurs exemples vivants.
