# The API changes that come with the same upgrade

The schema is half the job. These are the code changes Spring Batch 5.0 forces, verified in
`spring-batch-core:5.0.2` sources rather than quoted from a migration guide. Versions matter
here: several things are *deprecated* in 5.0 and removed later, so a 5.0 upgrade and a 5.2
upgrade are not the same amount of work.

## `JobBuilderFactory` / `StepBuilderFactory`

Still present in 5.0.2, and marked:

```java
@Deprecated(since = "5.0.0", forRemoval = true)
public class JobBuilderFactory {
```

So a 5.0 upgrade compiles with warnings; it is 5.2 that breaks. Do it now anyway — the
replacement is simpler, because the builders take the `JobRepository` explicitly:

```java
// 4.3
@Bean Job importJob(JobBuilderFactory jobs, Step step) {
    return jobs.get("importJob").start(step).build();
}

// 5.x -- constructors verified: JobBuilder(String, JobRepository),
//        StepBuilder(String, JobRepository)
@Bean Job importJob(JobRepository jobRepository, Step step) {
    return new JobBuilder("importJob", jobRepository).start(step).build();
}

@Bean Step importStep(JobRepository jobRepository, PlatformTransactionManager txManager,
                      ItemReader<Line> reader, ItemWriter<Line> writer) {
    return new StepBuilder("importStep", jobRepository)
            .<Line, Line>chunk(100, txManager)
            .reader(reader).writer(writer)
            .build();
}
```

Note `chunk(size, transactionManager)`: the chunk-oriented step now wants the transaction
manager at the point of declaration instead of inheriting one. This is the change that
produces the most compile errors, and the easiest to get wrong by injecting *a* transaction
manager rather than the one the `JobRepository` uses.

## `@EnableBatchProcessing` versus `DefaultBatchConfiguration`

In 5.x the annotation no longer hands you a `JobRepository`, a `JobLauncher` and a
transaction manager to inject anonymously. Two supported shapes:

- keep `@EnableBatchProcessing` and let Boot's autoconfiguration build the infrastructure;
- or extend `DefaultBatchConfiguration` and override only what you need — and then **do not**
  also put `@EnableBatchProcessing` on it, because the two ways of configuring the
  infrastructure conflict.

In a Spring Boot 3 application the practical rule is: **remove `@EnableBatchProcessing`** and
let autoconfiguration do it, unless you are overriding infrastructure beans. If you redefine
one — a custom `JobLauncher` for a synchronous launch, say — define only that one, and let
the rest be autoconfigured.

## Typed `JobParameter<T>`

```java
public class JobParameter<T> implements Serializable {
    private T value;
    private Class<T> type;
    private boolean identifying;
```

`JobParameters` is a `Map<String, JobParameter<?>>`. Code that read a parameter through the
old untyped accessors, or that switched on a `ParameterType` enum, has to move to the class.
`JobParametersBuilder` keeps `addString` / `addLong` / `addDouble` / `addDate` and **adds**
`addLocalDate`, `addLocalTime`, `addLocalDateTime` — new types that will appear in
`PARAMETER_TYPE` as `java.time.*`, which is worth knowing before writing anything that
validates that column against a fixed list.

## Things to check rather than assume

- **The `JobRepository`'s isolation level.** Default is `SERIALIZABLE` for the
  create-execution path; if 4.3 was tuned here, carry the setting over explicitly.
- **`ExecutionContextSerializer`.** 5.0's `JdbcExecutionContextDao` defaults to
  `DefaultExecutionContextSerializer`. If 4.x wired a different one, contexts written then
  are unreadable now — and it only shows on a restart.
- **Metadata schema initialisation.** If the schema comes from your own migration tool (it
  should, so that it is versioned and reviewable), make sure Boot's batch initializer is not
  also trying to create it: `spring.batch.jdbc.initialize-schema=never`.
- **`JobExplorer` / `JobOperator` wiring**, if the application exposes job history: the
  builders changed, the DAOs did not, but the beans are no longer handed to you.
- **ShedLock, Quartz, or whatever launches the jobs.** Their Spring 6 compatible lines are a
  separate upgrade, usually a major bump, and they fail at runtime rather than at compile
  time.

## Most of this is recipe-able -- the data migration is not

`rewrite-spring` ships `org.openrewrite.java.spring.boot3.SpringBatch4To5Migration` (verified present
in 4.36.0 by listing the recipe ids inside the jar). It handles the builders, the typed parameters and
the annotation changes above:

```bash
mvn rewrite:dryRun -Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.SpringBatch4To5Migration
```

**And that is exactly what makes this upgrade dangerous.** The code migrates in minutes, the build goes
green, the application starts — and the metadata is still in the 4.3 layout, or worse, has been through
the framework's own SQL script and lost its parameter values. A recipe cannot migrate data: the schema
change collapses four typed columns into one, and the right value depends on a type the rows no longer
carry.

So: run the recipe for the code, and treat the metadata as a separate, reversible, proven piece of
work -- the rest of this skill.

## Order of work

1. Schema and data migration first, reversible and proven (that is the rest of this skill) —
   it is the part with no undo once an application has written to the new layout.
2. Then the API changes, which the compiler finds for you.
3. Then one real job, and one deliberate fail-and-restart cycle against migrated history. A
   restart is the only thing that exercises the parameters, the execution context and the
   `JOB_KEY` uniqueness all at once, which is precisely what a metadata migration puts at
   risk.
