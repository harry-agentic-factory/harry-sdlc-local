# Spring Batch 4.3 → 5.0 — code migration

Source: official Spring Batch 5.0 migration guide + what's-new. Everything here is a breaking
change you will hit in application code.

## 1. Builders: factories are gone

`JobBuilderFactory` and `StepBuilderFactory` are no longer exposed as beans (deprecated, removed
in 5.2). Builders now take the `JobRepository` explicitly, and every tasklet/chunk step takes an
explicit `PlatformTransactionManager`.

```java
// Batch 4.x
@Autowired private JobBuilderFactory jobs;
@Autowired private StepBuilderFactory steps;

@Bean
public Job importJob() {
    return jobs.get("importJob").start(importStep()).build();
}

@Bean
public Step importStep() {
    return steps.get("importStep")
            .<Input, Output>chunk(100)
            .reader(reader()).processor(processor()).writer(writer())
            .build();
}
```

```java
// Batch 5.x
@Bean
public Job importJob(JobRepository jobRepository, Step importStep) {
    return new JobBuilder("importJob", jobRepository).start(importStep).build();
}

@Bean
public Step importStep(JobRepository jobRepository, PlatformTransactionManager txManager) {
    return new StepBuilder("importStep", jobRepository)
            .<Input, Output>chunk(100, txManager)
            .reader(reader()).processor(processor()).writer(writer())
            .build();
}
```

Also:
- `StepBuilder#tasklet(Tasklet)` → `tasklet(myTasklet, txManager)`.
- `BatchConfigurer` is removed: customize via `@EnableBatchProcessing` attributes or by
  extending `DefaultBatchConfiguration` (e.g. override `getTransactionManager()`).
- `SimpleJobLauncher` → `TaskExecutorJobLauncher`.
- `ItemWriter#write(List<T>)` → `ItemWriter#write(Chunk<? extends T>)`; same for
  `ItemWriteListener`. Custom writers must change their signature.
- Metric counters (`readCount`, `writeCount`, `skipCount`…) are `long` now (were `int`);
  `SkipPolicy#shouldSkip` takes a `long`.
- `JobExecution`/`StepExecution` dates are `java.time.LocalDateTime` (were `java.util.Date`).

## 2. Spring Boot 3 interplay

- Boot 3 auto-configures Batch **only when `@EnableBatchProcessing` is absent**. Adding it (or
  extending `DefaultBatchConfiguration`) tells Boot to back off: no auto `JobRepository`, no
  job launched at startup. Most Boot apps should now **remove** `@EnableBatchProcessing`.
- One `Job` bean in the context → launched at startup by `JobLauncherApplicationRunner`.
  Several → pick one with `spring.batch.job.name` (the plural `spring.batch.job.names` of
  Boot 2 is gone).
- In-memory Map repository is removed: tests and dev profiles need a JDBC repository on an
  embedded DB (H2/HSQL) instead.

## 3. Strongly-typed job parameters

Batch 4 had exactly four parameter types (STRING, LONG, DOUBLE, DATE), encoded in 4 dedicated
metadata columns. Batch 5 makes `JobParameter<T>` generic:

- any type is accepted; the type is persisted as the **fully qualified class name**;
- default CLI notation: `name=value,type,identifying` — e.g.
  `inputFile=/data/in.csv,java.lang.String,true`;
- JSON notation via `JsonJobParametersConverter`:
  `name='{"value":"in.csv","type":"java.lang.String","identifying":"true"}'`;
- conversion uses the standard `ConversionService` — register converters for custom types;
- `ParameterType` enum no longer exists; code switching on it must switch on the class.

Consequence for the metadata schema: see `batch-metadata-migration.md` — the typed columns are
replaced by `PARAMETER_NAME` / `PARAMETER_TYPE` (FQCN) / `PARAMETER_VALUE` (string).

## 4. Execution context serialization

Default serializer changed from Jackson to `DefaultExecutionContextSerializer` (Base64).
If your jobs rely on readable/JSON execution contexts (or you inspect them in DB), add the
optional Jackson dependency back and configure `JacksonExecutionContextStringSerializer`
explicitly. Contexts written by v4 remain readable only if the serializer matches — align this
BEFORE restarting old jobs.

## 5. Removals to grep for

`MapJobRepositoryFactoryBean`, `MapJobExplorerFactoryBean`, JSR-352 (`javax.batch`) support,
Neo4j/GemFire/SQLFire item readers-writers, `org.springframework.batch.core.metrics` (moved to
`...core.observability`, Micrometer tags now prefixed `spring.batch.*`).
