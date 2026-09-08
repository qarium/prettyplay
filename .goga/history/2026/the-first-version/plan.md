# Plan: `the-first-version`

Результат компиляции проверенного дизайн-документа
(`.goga/history/2026/the-first-version/design.md`, 2110 строк, прошедшего design-review
без открытых ремарок) в ralphex-план исполнения. Greenfield-реализация библиотеки
Prettyplay по контрактам CODEMANIFEST восьми клеток.

---

## Purpose

Реализовать с нуля библиотеку **prettyplay** — UI-тесты на человеческом языке с репозиторным
кэшем шагов, генерацией кода через LLM и самолечением:

- после реализации пакет предоставляет фасад `from prettyplay import PrettyTest` — главный
  объект интегратора (`action`/`assertion` предложениями), движок генерации/лечения,
  репозиторный кэш шагов, таксономию сбоев и видимость (логгер `prettyplay` + хуки);
- главные пробелы между контрактом и кодом: **кода нет вообще** — 24 контрактные сущности
  в 8 клетках не реализованы, нет `tests/`, нет зависимостей в `pyproject.toml`, нет venv;
- стратегия: строго снизу вверх по DAG клеток (config → reporting → failures → driver →
  cache → llm → engine → корень), каждая сущность — TDD-задача (контрактные тесты →
  реализация → логические тесты), после каждой клетки — `goga lint` + фасад-проверка
  импорта; финал — интеграционные тесты полного цикла шага.

## Context

### Contract Surface

Порядок клеток — снизу вверх (подтверждён `goga schema`): `config, reporting, failures` —
листья; `driver ← config`; `cache ← config, reporting`; `llm ← config, failures`;
`engine ← config, reporting, failures, driver, cache, llm`; `prettyplay ← все семь`.

#### Cell: `prettyplay/config`

**Entity: `Config`**
- Type: class (pydantic v2 BaseModel)
- Declared `location`: `prettyplay/config/models.py`
- Facade obligation: importable from `prettyplay.config`
- Signature: `Config(provider, browser, model, generation_model, classification_model, base_url, cache_root, generation_attempts, healing_attempts, send_screenshots)` — kw_only, все поля с пустыми дефолтами (`None` только для явной отсутствующности — здесь не используется)
- Properties (12): `provider -> str` (openai|anthropic, дефолт openai), `browser -> str` (chromium|firefox|webkit, дефолт chromium), `model -> str` (""), `generation_model -> str` (""), `classification_model -> str` (""), `base_url -> str` (""), `cache_root -> str` (""), `generation_attempts -> int` (3), `healing_attempts -> int` (2), `send_screenshots -> bool` (False), вычисляемые `effective_generation_model -> str` (generation_model или model), `effective_classification_model -> str`
- Semantic requirements: провайдер/браузер — Literal-валидация, невалидное — громкая actionable-ошибка с именем поля; attempts — положительные целые; секреты никогда не в полях
- Imported dependencies: нет (лист)
- Annotation context: глобальные `conventions`, `pydantic`

**Routine: `load_config`**
- Type: function
- Declared `location`: `prettyplay/config/loader.py`
- Facade obligation: importable from `prettyplay.config`
- Signature: `load_config(pyproject_path: str | None) -> config: Config`
- Semantic requirements: авто-поиск pyproject.toml вверх от cwd при `None`; tomllib (3.11+) / tomli (3.10); секция `[tool.prettyplay]` — отсутствующая = пустая; env-оверрайды `PRETTYPLAY_<SETTING_UPPER>` применяются, **когда переменная задана** (включая пустое значение); пустая `cache_root` → абсолютный `<pyproject_dir>/.prettyplay/cache/`; отсутствие pyproject.toml при авто-поиске — громкая ошибка; ключи LLM никогда не читаются из файлов

#### Cell: `prettyplay/reporting`

**Entity: `StepHooks`**
- Type: class (база callback-контракта)
- Declared `location`: `prettyplay/reporting/hooks.py`
- Facade obligation: importable from `prettyplay.reporting`
- Signature: `StepHooks()`
- Methods (8, все no-op `pass`): `on_step_started(step_text: str, step_type: str)`, `on_step_passed(step_text: str, step_type: str)`, `on_step_failed(step_text: str, step_type: str, error: str)`, `on_generation_started(step_text: str, attempt: int)`, `on_healing_started(step_text: str, category: str)`, `on_healed(step_text: str, explanation: str)`, `on_cache_saved(step_text: str, filename: str)`, `on_cache_skipped(step_text: str, reason: str)`
- Semantic requirements: синхронный вызов, без очередей/ретраев; интегратор переопределяет нужные события

**Entity: `StepReporter`**
- Type: class
- Declared `location`: `prettyplay/reporting/reporter.py`
- Facade obligation: importable from `prettyplay.reporting`
- Signature: `StepReporter(hooks: list[StepHooks])` — публичный атрибут `self.hooks` (список по ссылке, `add_hooks` аппендит в него)
- Methods: `emit(event: str, payload: dict[str, str | int])`
- Semantic requirements: логгер `logging.getLogger("prettyplay")`, событие = имя сообщения, payload как контекст `extra`; уровни: жизненный цикл INFO, `on_cache_skipped` и сбой хука WARNING; fan-out по хукам в порядке регистрации `getattr(hook, event)(**payload)`; исключение хука → WARNING + пропуск, прогон продолжается; санитизация ключей `extra` (зарезервированные атрибуты LogRecord получают префикс `ctx_` — иначе `KeyError` от `Logger.makeRecord`; хуки получают оригинальные kwargs); секреты не логируются

#### Cell: `prettyplay/failures`

**Entity: `PrettyplayError`** — база таксономии
- Type: class (Exception)
- Declared `location`: `prettyplay/failures/errors.py`
- Facade obligation: importable from `prettyplay.failures`
- Signature: `PrettyplayError(message: str)`

**Mutation: `PrettyplayError::ProductDefectError(step_text: str, message: str)`**
- Properties: `step_text -> str`, `message -> str`
- Semantics: реальный функциональный дефект продукта; никакой retry/healing; сообщение называет ожидание и наблюдаемое состояние

**Mutation: `PrettyplayError::IncurableStepError(step_text: str, reason: str, recommendation: str)`**
- Properties: `step_text -> str`, `reason -> str`, `recommendation -> str`
- Semantics: `str()` рендерит все три поля

**Mutation: `PrettyplayError::LlmUnavailableError(message: str)`**
- Properties: `message -> str` (называет провайдера)
- Semantics: блокирует только генерацию/лечение; кэшированные шаги продолжают исполняться; без повторов

Все четыре имени — на фасаде `prettyplay.failures`.

#### Cell: `prettyplay/driver`

**Entity: `DriverSession`**
- Type: class
- Declared `location`: `prettyplay/driver/session.py`
- Facade obligation: importable from `prettyplay.driver`
- Signature: `DriverSession(config: Config)`; Imports: `Config` from `prettyplay/config`
- Methods: `open_context() -> page: PageFacade` (ленивый запуск браузера ровно один раз на прогон: `sync_playwright().start()`, словарь движков `{chromium, firefox, webkit}`; каждая страница — свой изолированный контекст), `close()` (браузер + драйвер; безопасен при незапуске, идемпотентен)
- Errors: ошибки Playwright пробрасываются как есть

**Entity: `PageFacade`**
- Type: class
- Declared `location`: `prettyplay/driver/page.py`
- Facade obligation: importable from `prettyplay.driver`
- Signature: `PageFacade(page, context)` (обёртка; конструктор вне контракта генерации)
- Properties: `url -> str`
- Methods: `open(url: str)` → `page.goto`; `find_by_role(role: str, name: str) -> element: LocatorFacade` → `get_by_role(role, name=name)`; `find_by_label(label: str) -> element: LocatorFacade`; `find_by_text(text: str) -> element: LocatorFacade`; `aria_snapshot() -> snapshot: str` → `page.locator("body").aria_snapshot()`; `screenshot() -> image: bytes` → `page.screenshot(full_page=True)`; `close()` → `context.close()` (браузер жив)

**Entity: `LocatorFacade`**
- Type: class
- Declared `location`: `prettyplay/driver/page.py` (тот же файл, что PageFacade)
- Facade obligation: importable from `prettyplay.driver`
- Methods: `click()`; `fill(value: str)`; `select_option(value: str)`; `expect_visible()` → `expect(loc).to_be_visible()`; `expect_text(text: str)` → `expect(loc).to_contain_text(text)` (дизъюнкция equals|contains = contains); `expect_enabled()` → `expect(loc).to_be_enabled()`
- Constraints: никаких фиксированных задержек; наружу не отдаётся ни один сырой объект Playwright (возвраты — str / bytes / LocatorFacade); фасад — backward-compatibility контракт (расширять, никогда не переименовывать/удалять)

#### Cell: `prettyplay/cache`

**Routine: `normalize_step_text`**
- Declared `location`: `prettyplay/cache/text.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `normalize_step_text(text: str) -> normalized: str`
- Algorithm: NFC → strip → collapse `\s+`→" " → casefold; чистая функция (без I/O и локали)

**Entity: `StepIdentity`**
- Declared `location`: `prettyplay/cache/models.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `StepIdentity(cache_key: str, step_type: str, normalized_text: str)` — pydantic kw_only
- Properties: `cache_key -> str`, `step_type -> str`, `normalized_text -> str`, `filename -> str` (вычисляемое: `"\x1f".join((cache_key, step_type, normalized_text))` → sha256 hexdigest → `f"{digest}.py"`)

**Entity: `CachedStep`**
- Declared `location`: `prettyplay/cache/models.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `CachedStep(identity: StepIdentity, code: str, created_at: str)` — pydantic kw_only
- Requirement: файл кэша — валидный python-модуль (метаданные, затем код); без поля версии библиотеки

**Entity: `StepCache`**
- Declared `location`: `prettyplay/cache/store.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `StepCache(config: Config, path: str | None, reporter: StepReporter)`; Imports: `Config` from `prettyplay/config`, `StepReporter` + usages `hooks` from `prettyplay/reporting`
- Properties: `root -> str`, `writable -> bool` (ленивая проверка: mkdir parents exist_ok + `os.access(W_OK)`; OSError → False)
- Methods: `load(identity) -> step: CachedStep | None` (отсутствие файла → None; Protective block разбора: header-константы `STEP_TEXT`/`CACHE_KEY`/`STEP_TYPE`/`CREATED_AT` через `ast.literal_eval`, хвост с первого вхождения `def step(` без ведущего перевода строки; любая структурная ошибка или расхождение метаданных с identity → None — защитный промах, прогон не падает); `save(step: CachedStep)` (read-only → `emit("on_cache_skipped", reason="read-only cache")` и выход; сериализация: repr-литералы заголовка + код; `tempfile.mkstemp(dir=target_dir, prefix=".tmp-", suffix=".py")` + fsync + `os.replace`; Windows retry 3×0.1 c при PermissionError, затем skip + `on_cache_skipped(reason="cache target busy")`; успех → `emit("on_cache_saved", {"step_text", "filename"})`)

**Entity: `RunBudgets`**
- Declared `location`: `prettyplay/cache/budgets.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `RunBudgets(generation_limit: int, healing_limit: int)`
- Methods: `try_generation(identity: StepIdentity) -> allowed: bool`, `try_healing(identity: StepIdentity) -> allowed: bool`
- Semantics: per-run реестр (один процесс), ключ — `identity.filename`; раздельные пулы gen/heal; бюджеты не сбрасываются между тестами; никакой персистенции

#### Cell: `prettyplay/llm`

**Entity: `LlmProvider`** (порт)
- Declared `location`: `prettyplay/llm/provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Methods: `generate_step_code(prompt, step_text, previous_steps, snapshot, screenshot, page_api, existing_code, error) -> code: str`; `classify_failure(prompt, step_text, code, error, snapshot, screenshot) -> classification: FailureClassification`
- Semantics: prompt передаётся verbatim как system-сообщение; один запрос на попытку (бюджеты — вне провайдера); сбой сервиса → `LlmUnavailableError` с именем провайдера; сгенерированный код без провайдерных конструкций

**Mutation: `LlmProvider::OpenAiProvider(config: Config)`**
- Declared `location`: `prettyplay/llm/openai_provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Паритет с AnthropicProvider: ленивый клиент (`OPENAI_API_KEY` при первом запросе; отсутствие/пустота → `LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")`); `client.chat.completions.create(model=effective_generation_model, messages=[system, user])`; скриншот — блок `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}`; извлечение `response.choices[0].message.content`; `openai.OpenAIError` → `LlmUnavailableError ... from e`

**Mutation: `LlmProvider::AnthropicProvider(config: Config)`**
- Declared `location`: `prettyplay/llm/anthropic_provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Полный паритет: `ANTHROPIC_API_KEY`; `client.messages.create(model=..., system=prompt, max_tokens=1024, messages=[user])`; скриншот — блок `{"type":"image","source":{"type":"base64","media_type":"image/png","data":...}}`; извлечение `message.content[0].text`; `anthropic.AnthropicError` → `LlmUnavailableError ... from e`

**Routine: `create_provider`**
- Declared `location`: `prettyplay/llm/provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Signature: `create_provider(config: Config) -> provider: LlmProvider`
- Semantics: `"openai"` → OpenAiProvider, `"anthropic"` → AnthropicProvider, иное — `ValueError` со списком поддерживаемых (belt and suspenders к Literal)

**Entity: `FailureClassification`**
- Declared `location`: `prettyplay/llm/models.py`
- Facade obligation: importable from `prettyplay.llm`
- Signature: `FailureClassification(category: str, explanation: str, recommendation: str)` — pydantic kw_only
- Properties: `category -> str` (rot | product_defect | incurable), `explanation -> str`, `recommendation -> str`

#### Cell: `prettyplay/engine`

**Routine: `run_step_code`**
- Declared `location`: `prettyplay/engine/execution.py`
- Facade obligation: importable from `prettyplay.engine`
- Signature: `run_step_code(code: str, page: PageFacade)`
- Algorithm: `namespace = {}`; `exec(compile(code, "<prettyplay-step>", "exec"), namespace)`; `fn = namespace["step"]`; `fn(page)` — исключения пробрасываются как есть (no swallow, no retry, no LLM, no network); модуль не регистрируется в `sys.modules`

**Entity: `StepGenerator`**
- Declared `location`: `prettyplay/engine/generator.py`
- Facade obligation: importable from `prettyplay.engine`
- Signature: `StepGenerator(config: Config, provider: LlmProvider, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)`
- Methods: `generate(identity, step_text, previous_steps, page) -> step: CachedStep`; `regenerate(identity, step_text, previous_steps, page, existing_code, error) -> step: CachedStep`
- Semantics: PAGE_API_SURFACE — замороженная строка-константа поверхности фасада; цикл попыток с `try_generation`/`try_healing`, `emit("on_generation_started", {"step_text", "attempt": n})`, snapshot (+screenshot при флаге), первая попытка `existing_code=None, error=None`, каждый повтор — regeneration-request с упавшим кандидатом и свежей ошибкой; успех → `CachedStep(..., created_at=date.today().isoformat())` → `cache.save`; `LlmUnavailableError` — немедленный проброс; исчерпание → `IncurableStepError`
- Inline Usages: `generation_prompt`, `classification_prompt` (тексты — в соответствующей задаче, verbatim)

**Entity: `StepHealer`**
- Declared `location`: `prettyplay/engine/healer.py`
- Facade obligation: importable from `prettyplay.engine`
- Signature: `StepHealer(config: Config, provider: LlmProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)`
- Methods: `heal(step: CachedStep, error: str, previous_steps: list[str], page: PageFacade) -> step: CachedStep`
- Semantics: сборка входов классификации → `classify_failure` (classification_prompt) → `emit("on_healing_started", {"step_text", "category"})` → product_defect → `ProductDefectError` (кэш нетронут); incurable → `IncurableStepError(step_text, reason, recommendation)`; rot → `generator.regenerate(...)` → `emit("on_healed", {"step_text", "explanation"})` → return healed; анти-маскировка

#### Cell: `prettyplay` (корень)

**Entity: `PrettyTest`**
- Declared `location`: `prettyplay/scenario.py`
- Facade obligation: importable from `prettyplay`
- Signature: `PrettyTest(cache_key: str, cache_path: str | None)`
- Properties: `cache_key -> str`
- Methods: `action(text: str)`, `assertion(text: str)`, `add_hooks(hooks: StepHooks)`, `close()`; протокол контекст-менеджера (`__enter__`/`__exit__` → close, не гасит исключения)
- Semantics: композиция per-test объектов поверх `get_runtime()`; страница лениво на первом шаге; конструкция дешёвая; нет кросс-тестового состояния

**Entity: `StepExecutor`**
- Declared `location`: `prettyplay/executor.py`
- Facade obligation: importable from `prettyplay`
- Signature: `StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, budgets: RunBudgets, reporter: StepReporter)`
- Methods: `execute(step_text: str, step_type: str, page: PageFacade)`
- Semantics: on_step_started → identity → load → hit: run_step_code (сбой → heal с контекстом) | miss: generate → append сценарного контекста → on_step_passed; любой сбой → on_step_failed + проброс по виду; документированная интерпретация: классификация (и ProductDefectError) — только после первой успешной генерации и кэширования шага; никогда не сгенерировавшийся шаг даёт IncurableStepError

**Entity: `PrettyplayRuntime`**
- Declared `location`: `prettyplay/runtime.py`
- Facade obligation: importable from `prettyplay`
- Signature: `PrettyplayRuntime(config: Config)`
- Properties: `config -> Config` (eager), `budgets -> RunBudgets` (eager), `driver -> DriverSession` (лениво), `provider -> LlmProvider` (лениво, через `create_provider`)
- Methods: `open_page() -> page: PageFacade`, `close()`
- Semantics: конструкция без LLM-кредов

**Routine: `get_runtime`**
- Declared `location`: `prettyplay/runtime.py`
- Facade obligation: importable from `prettyplay`
- Signature: `get_runtime() -> runtime: PrettyplayRuntime` — процессный синглтон (модульная глобаль `_runtime`)

### Interaction Diagram (verbatim из дизайна)

```
                    интегратор (тест)
                          │  PrettyTest(cache_key[, cache_path]) / action / assertion
                          ▼
┌───────────────────────────── prettyplay (корень) ─────────────────────────────────────┐
│                                                                                      │
│  PrettyTest ──get_runtime()──► PrettyplayRuntime (процессный синглтон)               │
│     │                            │         │         │                               │
│     │ StepReporter(hooks=[])  Config   DriverSession RunBudgets    LlmProvider        │
│     │      ▲                (load_config)   │         │         (create_provider)    │
│     │      │ emit(...)                     ▼         │        ┌─ OpenAiProvider      │
│     │      ├──────────────► logger "prettyplay" + StepHooks     └─ AnthropicProvider  │
│     │                                                                                 │
│     └─► StepExecutor.execute(step_text, step_type, page)                             │
│              │ 1. identity = StepIdentity(cache_key, step_type,                       │
│              │      normalize_step_text(text))                                        │
│              │ 2. cache.load(identity) ──────────── hit ──► run_step_code(code, page) │
│              │                                          │                    │        │
│              │                                       успех │             сбой │        │
│              │                                          ▼                    ▼        │
│              │                                   append scenario   StepHealer.heal    │
│              │ ─────────── miss ──► StepGenerator.generate    (step, error,   prev,  │
│              │                         │  ▲   retry            page)                │
│              │                         │  └─────────────┘        │ classify_failure  │
│              │                    cache.save(CachedStep)         ▼                   │
│              │                                              verdict ─┬─ rot ──►        │
│              │  DriverSession.open_context() ──► PageFacade        │   regenerate    │
│              │  (лениво, на первом шаге теста)                   ├─ product_defect   │
│              │                                                  ▶ ProductDefectError│
│              │                                                  └─ incurable        │
│              │                                                     ▶ IncurableStepError
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Порядок создания объектов в рантайме: `load_config` → `PrettyplayRuntime` (config eagerly;
`RunBudgets` eagerly; `DriverSession` и `LlmProvider` — лениво) → на тест: `StepReporter` →
`StepCache` → `StepGenerator` → `StepHealer` → `StepExecutor` → лениво `PageFacade` (первый шаг).

### Re-exports

DSL-блоков `->Name: {}` в манифестах нет. Фасадные обязательства возникают из языковых правил
Python (`__init__.py` + `__all__`) и Additional Instructions дизайна — полный список:

| Пакет | Реэкспорт (`__all__`) |
|---|---|
| `prettyplay` | `PrettyTest` (scenario), `StepExecutor` (executor), `PrettyplayRuntime`, `get_runtime` (runtime) |
| `prettyplay.config` | `Config` (models), `load_config` (loader) |
| `prettyplay.reporting` | `StepHooks` (hooks), `StepReporter` (reporter) |
| `prettyplay.failures` | `PrettyplayError`, `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (errors) |
| `prettyplay.driver` | `DriverSession` (session), `PageFacade`, `LocatorFacade` (page) |
| `prettyplay.cache` | `normalize_step_text` (text), `StepIdentity`, `CachedStep` (models), `StepCache` (store), `RunBudgets` (budgets) |
| `prettyplay.llm` | `LlmProvider`, `create_provider` (provider), `OpenAiProvider` (openai_provider), `AnthropicProvider` (anthropic_provider), `FailureClassification` (models) |
| `prettyplay.engine` | `run_step_code` (execution), `StepGenerator` (generator), `StepHealer` (healer) |

Импорты внутри пакета — только относительные; фасад-проверка после каждой клетки:
`.venv/bin/python -c "from prettyplay.<клетка> import <сущность>"`.

### Usages Context

- **`conventions`** (`.goga/usages/conventions.md`) — обязательные правила кода и тестов:
  Python 3.10+, относительные импорты внутри пакета, pydantic v2 `kw_only=True` + пустые
  дефолты (`None` только для явной отсутствующности), logging с контекстом (`extra`),
  Google-docstring, ruff, структура tests/ зеркальная (`prettyplay/cache/store.py` →
  `tests/cache/test_store.py`, корневые модули — прямо в `tests/`), моки только на внешних
  границах, файловые тесты — только `tmp_path`. Валидация: `pytest tests/ -x`,
  `ruff check <src>/`, фасад `python -c "from package import Entity"`. Все third-party
  библиотеки — в `pyproject.toml` с минимальной версией. Релевантно **каждой** задаче.
- **`pydantic`** (`.goga/usages/cooks/pydantic.md`) — паттерны моделей v2
  (`model_config = ConfigDict(kw_only=True)`, пустые дефолты) и загрузка TOML с
  tomli-фолбэком для 3.10 (`sys.version_info >= (3, 11)` → `tomllib`, иначе `tomli`).
  Релевантно: `Config`, `load_config`, `StepIdentity`, `CachedStep`, `FailureClassification`.
- **`playwright`** (`.goga/usages/cooks/playwright.md`) — sync-API lifecycle
  (`sync_playwright()`), матрица браузеров `{chromium, firefox, webkit}` через словарь,
  локаторы с auto-wait, `expect(...)` для ожиданий, `page.locator("body").aria_snapshot()`,
  изолированный контекст на тест, никаких `time.sleep`. Релевантно: `DriverSession`,
  `PageFacade`, `LocatorFacade`.
- **`openai`** (`.goga/usages/cooks/openai.md`) — паттерны SDK: ключи только из env,
  `client.chat.completions.create(model=..., messages=[system, user])`, извлечение
  `choices[0].message.content`, маппинг `OpenAIError` → `LlmUnavailableError`. Релевантно:
  `OpenAiProvider`.
- **`anthropic`** (`.goga/usages/cooks/anthropic.md`) — паттерны SDK: ключи только из env,
  `client.messages.create(model=..., max_tokens=1024, system=..., messages=[user])`,
  извлечение `content[0].text`, маппинг `AnthropicError` → `LlmUnavailableError`.
  Релевантно: `AnthropicProvider`.
- **`generation_prompt`** (inline, engine) — системный промпт генерации; фиксирует форму
  ответа (`def step(page) -> None:`), входы (STEP/PREVIOUS STEPS/PAGE SNAPSHOT/SCREENSHOT/
  PAGE API/CODE/ERROR) и правила (только поверхность фасада, без импортов, без задержек).
  Текст приведён verbatim в Задаче 17. Релевантно: `StepGenerator`.
- **`classification_prompt`** (inline, engine) — системный промпт классификации; ответ одной
  строкой `category | explanation | recommendation`, категории rot/product_defect/incurable.
  Текст приведён verbatim в Задаче 17. Релевантно: `StepHealer`.

### Imported Usages

- **`hooks`** from `prettyplay/reporting` (`prettyplay/reporting/.usages/hooks.md`) — контракт
  событий: имена методов = имена событий; payload-значения — строки, счётчик попытки
  `on_generation_started` — int. Потребители: cache (события записи кэша), корень
  (`add_hooks`).
- **`taxonomy`** from `prettyplay/failures` (`prettyplay/failures/.usages/taxonomy.md`) —
  три вида сбоев и их поля (в т.ч. `info.value.recommendation` у IncurableStepError);
  потребители: llm (LlmUnavailableError), engine (ProductDefectError/IncurableStepError),
  корень (проброс по виду).
- **`generation`, `healing`** from `prettyplay/engine`
  (`prettyplay/engine/.usages/{generation,healing}.md`) — циклы движка, которым делегирует
  `StepExecutor`; бюджеты — один run-scoped реестр с раздельными пер-шаговыми лимитами
  (3 и 2 по умолчанию); `heal` принимает `previous_steps`.
- **`facade`** from `prettyplay/driver` (`prettyplay/driver/.usages/facade.md`) — единый
  источник поверхности PAGE API для запросов генерации (PAGE_API_SURFACE в generator.py
  синхронизируется с этой поверхностью).
- **`classification`** from `prettyplay/llm` (`prettyplay/llm/.usages/classification.md`) —
  категории решения лечения (rot / product_defect / incurable) и защитный дефолт incurable.

### Local Usages

Новых файлов `.usages/` дизайн не требует («существующая доменная разбивка покрывает все
сущности; правки внутри доменов»). Существующие 13 файлов актуальны после стадии дизайна:

| Файл | Домен | Статус |
|---|---|---|
| `prettyplay/.usages/steps.md` | API `PrettyTest` (action/assertion) | актуален |
| `prettyplay/.usages/lifecycle.md` | композиция, add_hooks до первого шага, виды сбоев | актуален |
| `prettyplay/config/.usages/configuration.md` | схема, 10 env-оверрайдов, дефолты | актуален |
| `prettyplay/reporting/.usages/hooks.md` | контракт хуков | обновлён стадией дизайна (int-попытка) |
| `prettyplay/failures/.usages/taxonomy.md` | таксономия | актуален (после D3) |
| `prettyplay/driver/.usages/facade.md` | поверхность фасада | актуален |
| `prettyplay/cache/.usages/addressing.md` | адресация шага | актуален |
| `prettyplay/cache/.usages/storage.md` | формат файла, атомарность | актуален |
| `prettyplay/cache/.usages/budgets.md` | реестр попыток | актуален |
| `prettyplay/llm/.usages/providers.md` | паритет провайдеров | актуален |
| `prettyplay/llm/.usages/classification.md` | вердикт классификации | актуален |
| `prettyplay/engine/.usages/generation.md` | цикл генерации | актуален |
| `prettyplay/engine/.usages/healing.md` | цикл лечения | обновлён стадией дизайна (previous_steps, раздельные лимиты) |

Задач на создание/обновление usage-файлов в плане нет. Ограничение реализации: при изменении
поверхности фасада драйвера синхронизировать `PAGE_API_SURFACE` (generator.py) и
`prettyplay/driver/.usages/facade.md` — но сам фасад в этом плане не меняется.

### External Dependencies

- **pydantic ≥2.7** — все модели данных (`Config`, `StepIdentity`, `CachedStep`, `FailureClassification`)
- **playwright ≥1.44** — браузерный драйвер (sync API)
- **openai ≥1.30** — SDK провайдера OpenAI
- **anthropic ≥0.28** — SDK провайдера Anthropic
- **tomli ≥2.0** (маркер `python_version < "3.11"`) — TOML для Python 3.10
- Тестовые (уже объявлены в `pyproject.toml` → `[project.optional-dependencies].test`):
  pytest ≥8.0, pytest-cov ≥5.0, pytest-mock ≥3.10, ruff ≥0.15.0
- Инструменты процесса: venv (`python3 -m venv .venv`), `goga lint` (проверка клеток)

## Facts

- Greenfield: в `prettyplay/` существует только пустой `__init__.py`; клетки содержат только
  `CODEMANIFEST` + `.usages/`; каталога `tests/` нет; venv отсутствует.
- `pyproject.toml` существует: `[project]` name=prettyplay, `requires-python >=3.10`,
  `dependencies = []` (пусто — зависимости требуется добавить), test-extras объявлены,
  `[tool.ruff]` line-length=120, mccabe max-complexity=10, `[tool.pytest.ini_options]`
  testpaths=["tests"], addopts="-v --tb=short".
- Локальный интерпретатор — Python 3.12.14; глобально pytest/ruff/pydantic не установлены
  (нужен venv, `.venv` уже в `.gitignore`).
- `goga lint` — 8 клеток, 0 ошибок (контракты валидны и read-only).
- `goga config language` — python (правила: PascalCase классы, snake_case функции/методы,
  фасад через `__all__`, type hints обязательны, `self` исключён из сигнатур контракта).
- Кэш-файл шага: заголовок `STEP_TEXT` / `CACHE_KEY` / `STEP_TYPE` / `CREATED_AT`
  (repr-литералы), затем код фиксированной формы `def step(page) -> None:`; без поля версии.
- Runtime-инварианты дизайна: конструкция рантайма и PrettyTest не требует LLM-кредов;
  кэш-путь не трогает провайдера; один запрос к провайдеру на попытку; `LlmUnavailableError`
  без повторов; ключи только из env, никогда в логах.

## Gap Analysis

- **Missing contract entities**: все 24 (см. Contract Surface) — реализация с нуля.
- **Missing facade exposure**: все 8 `__init__.py` клеток (7 под-клеток не существуют, корень
  пуст) + `__all__`.
- **Incorrect `location` placement**: нет — файлов ещё нет; `location` из CODEMANIFEST
  обязательны буквально (файл на уровне каталога клетки, с расширением).
- **API mismatches / Behavioral mismatches**: нет существующего кода.
- **Existing code that can be reused**: `pyproject.toml` (сборка, ruff, pytest-конфиг,
  test-extras), `.gitignore` (нужно дополнить `.prettyplay/`), пустой `prettyplay/__init__.py`.
- **Test coverage gaps**: 100% — тестов нет; дизайн фиксирует 38 тест-сценариев
  (18 positive, 11 negative, 9 edge) + дополнительные по конвенциям (фасад-делегация,
  паритет anthropic, unit executor).
- **Missing visibility in workspace or git**: зависимости не в `pyproject.toml`
  (`dependencies = []`); venv не создан.

---

## Tasks

> **Package ordering rule**: задачи выполняются строго по порядку номеров; клетки завершаются
> снизу вверх (config → reporting → failures → driver → cache → llm → engine → корень).
> Внутри каждой coding-задачи контрактные тесты пишутся первыми (TDD workflow).
> Один ralphex-цикл = одна задача. CODEMANIFEST-файлы — read-only.

### Task 1: Инфраструктура проекта — зависимости, venv, скелет тестов (infrastructure)

Контекст: подготовить окружение для всех последующих задач. Проект greenfield: в `pyproject.toml`
`dependencies = []`, venv отсутствует, каталога `tests/` нет. По conventions все third-party
библиотеки обязаны быть в `pyproject.toml` с минимальной версией; весь код исполняется в venv;
тесты зеркалят структуру пакета (`tests/<клетка>/test_<module>.py`, корневые модули — прямо в
`tests/`, каждый каталог с `__init__.py`). Кэш-рут по умолчанию `<repo root>/.prettyplay/cache/`
должен быть в `.gitignore`.

**Usages relevant to this task:**
- `conventions`: разделы Development (venv, pyproject), Dependencies (минимальные версии),
  Test Structure (зеркальность, `__init__.py` в каждом каталоге тестов).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] Добавить runtime-зависимости в `pyproject.toml` → `[project].dependencies`:
      `"pydantic>=2.7"`, `"playwright>=1.44"`, `"openai>=1.30"`, `"anthropic>=0.28"`,
      `"tomli>=2.0; python_version < '3.11'"` (кавычки маркера — одинарные внутри double-quoted строки TOML)
- [x] Убедиться, что `[project.optional-dependencies].test` уже содержит pytest, pytest-cov,
      pytest-mock, ruff (ничего не добавлять, если уже есть)
- [x] Дополнить `.gitignore` строкой `.prettyplay/` (репозиторный кэш шагов не коммитится)
- [x] Создать venv и установить пакет с тестовыми зависимостями:
      `python3 -m venv .venv && .venv/bin/pip install -e ".[test]"`
- [x] Создать скелет тестов (пустые пакеты): `tests/__init__.py`, `tests/conftest.py` (пустой),
      и для каждой клетки `tests/{config,reporting,failures,driver,cache,llm,engine}/__init__.py`
- [x] Verify: `.venv/bin/pytest --collect-only tests/` завершается без ошибок коллекциирования
      (0 тестов — норма на этом этапе)
- [x] Verify: `.venv/bin/ruff check prettyplay/ tests/` — 0 ошибок
- [x] Lint: `.venv/bin/ruff check prettyplay/ tests/` — исправить форматирование при необходимости

### Task 2: `Config` — валидированные настройки (prettyplay/config/models.py)

Контекст: контрактная сущность `Config` клетки `prettyplay/config`, `location: models.py`,
обязанность фасада `from prettyplay.config import Config` (создать
`prettyplay/config/__init__.py` с реэкспортом и `__all__`). pydantic v2 BaseModel,
`model_config = ConfigDict(kw_only=True)`, все поля с пустыми дефолтами. Валидация:
`provider` — `Literal["openai", "anthropic"]` (дефолт "openai"); `browser` —
`Literal["chromium", "firefox", "webkit"]` (дефолт "chromium"); `generation_attempts=3`,
`healing_attempts=2` — PositiveInt; остальные поля-строки "" ; `send_screenshots=False`.
Вычисляемые свойства: `effective_generation_model = generation_model or model`,
`effective_classification_model = classification_model or model`. `None` не используется.
Секреты никогда не в полях.

**Usages relevant to this task:**
- `pydantic`: kw_only-модели, пустые дефолты.
- `conventions`: Google-docstring, type hints, ruff.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. pydantic v2 BaseModel, model_config = ConfigDict(kw_only=True)
   → все поля с пустыми дефолтами: provider="openai", browser="chromium", model="",
     generation_model="", classification_model="", base_url="", cache_root="",
     generation_attempts=3, healing_attempts=2, send_screenshots=False
2. Валидация: provider — Literal["openai","anthropic"]; browser — Literal["chromium","firefox","webkit"];
   attempts — PositiveInt (pydantic), сообщение включает имя поля
   → невалидное значение = громкая actionable-ошибка
3. Вычисляемые properties (cached_property или обычные):
   effective_generation_model = generation_model if generation_model else model
   effective_classification_model = classification_model if classification_model else model
```

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 2 — `Config`
- [x] **Contract tests** (`tests/config/test_models.py`): `from prettyplay.config import Config`
      работает; `Config` — pydantic BaseModel; конструкция ТОЛЬКО keyword-аргументами
      (позиционная `Config("openai")` → TypeError); у экземпляра доступны все 12 свойств
      (`provider`, `browser`, `model`, `generation_model`, `classification_model`, `base_url`,
      `cache_root`, `generation_attempts`, `healing_attempts`, `send_screenshots`,
      `effective_generation_model`, `effective_classification_model`). Ожидаемый провал на этом этапе
- [x] **Code**: создать `prettyplay/config/models.py` с `Config` по алгоритму выше
      (Google-docstring на классе; type hints обязательны)
- [x] **Code**: создать `prettyplay/config/__init__.py` — `from .models import Config`,
      `__all__ = ["Config"]`
- [x] **Interface verification**: `.venv/bin/pytest tests/config/test_models.py -v` — все
      контрактные тесты проходят; фасад: `.venv/bin/python -c "from prettyplay.config import Config"`
- [x] **Logic tests** (`tests/config/test_models.py`):
      - `test_config_defaults_valid` — Setup: ничего (чистая модель). Input: `Config()`.
        Assertions (verbatim из дизайна):
        ```
        config.provider == "openai"
        config.browser == "chromium"
        config.generation_attempts == 3 and config.healing_attempts == 2
        config.send_screenshots is False
        config.effective_generation_model == config.model == ""
        ```
      - `test_config_invalid_provider_fails_loudly` — Input: `Config(provider="yandex")`.
        Assertions: `pytest.raises(pydantic.ValidationError)`; `"provider"` в тексте ошибки;
        перечислены допустимые значения ("openai", "anthropic")
      - дополнительный edge (по конвенциям): `Config(generation_attempts=0)` → ValidationError
        с именем поля; `Config(browser="ie")` → ValidationError
- [x] **Debugging**: `.venv/bin/pytest tests/config/ -x` — исправлять реализацию (не тесты),
      пока всё не пройдёт
- [x] **Contract re-verification**: фасад `prettyplay.config` импортирует `Config` через
      `__all__`; kw_only; 12 свойств на месте; поведение совпадает с контрактом
- [x] **Lint**: `.venv/bin/ruff check prettyplay/config/ tests/config/` — исправить форматирование

### Task 3: `load_config` — загрузка pyproject.toml с env-оверрайдами (prettyplay/config/loader.py)

Контекст: Routine клетки `prettyplay/config`, `location: loader.py`, фасад
`from prettyplay.config import load_config` (добавить в существующий `__init__.py` клетки).
Сигнатура: `load_config(pyproject_path: str | None) -> Config`. Использует `Config` из
`prettyplay/config/models.py` (относительный импорт `from .models import Config`).
Клетка config завершается этой задачей.

**Usages relevant to this task:**
- `pydantic`: загрузка TOML — `sys.version_info >= (3, 11)` → `import tomllib`, иначе
  `import tomli as tomllib`; `tomllib.load(path.open("rb"))`.
- `conventions`: файловые тесты — только `tmp_path`; env — `monkeypatch`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. path = Path(pyproject_path) если задан, иначе первый существующий
   pyproject.toml среди [Path.cwd(), *Path.cwd().parents]
2. IF Python >= 3.11: import tomllib ELSE: import tomli as tomllib
3. data = tomllib.load(path.open("rb")); section = data.get("tool", {}).get("prettyplay", {})
4. FOR каждого из 10 полей: env PRETTYPLAY_<FIELD_UPPER> задана (включая пустое значение) → override
5. merged = {**section, **env_overrides}
6. cache_root пуста в merged → merged["cache_root"] = str(path.parent / ".prettyplay" / "cache")
7. RETURN Config(**merged)
```

Trace-чекпойнты дизайна (пройти по реализации): env-override применяется, когда
`os.environ.get(name) is not None` (контракт «when the variable is set» — включая пустое
значение; пустая строка в str-поле легальна, пустая в int/bool-поле — громкая ValidationError
с именем настройки — коэрсию делает pydantic lax: "3"→3, "false"→False); отсутствие секции —
не ошибка; отсутствие pyproject.toml при авто-поиске — громкая ошибка «pyproject.toml not
found»; ValidationError пробрасывается.

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 3 — `load_config`
- [x] **Contract tests** (`tests/config/test_loader.py`): `from prettyplay.config import load_config`
      доступен; сигнатура допускает `load_config(None)` и `load_config(str(path))`; возвращает
      `Config`. Ожидаемый провал на этом этапе
- [x] **Code**: создать `prettyplay/config/loader.py` по алгоритму выше; env-оверрайды для
      всех 10 полей (`PRETTYPLAY_PROVIDER`, `PRETTYPLAY_BROWSER`, `PRETTYPLAY_MODEL`,
      `PRETTYPLAY_GENERATION_MODEL`, `PRETTYPLAY_CLASSIFICATION_MODEL`, `PRETTYPLAY_BASE_URL`,
      `PRETTYPLAY_CACHE_ROOT`, `PRETTYPLAY_GENERATION_ATTEMPTS`, `PRETTYPLAY_HEALING_ATTEMPTS`,
      `PRETTYPLAY_SEND_SCREENSHOTS`)
- [x] **Code**: `prettyplay/config/__init__.py` — добавить `from .loader import load_config`,
      `__all__ = ["Config", "load_config"]`
- [x] **Interface verification**: `.venv/bin/pytest tests/config/test_loader.py -v`;
      фасад: `.venv/bin/python -c "from prettyplay.config import load_config"`
- [x] **Logic tests** (`tests/config/test_loader.py`):
      - `test_load_config_reads_section_and_env_overrides` — Setup: `tmp_path/pyproject.toml`
        ```toml
        [tool.prettyplay]
        provider = "openai"
        browser = "chromium"
        model = "gpt-5"
        ```
        `monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")`;
        `monkeypatch.setenv("PRETTYPLAY_GENERATION_ATTEMPTS", "5")`.
        Input: `load_config(pyproject_path=str(tmp_path / "pyproject.toml"))`.
        Assertions (verbatim):
        ```
        config.model == "gpt-5"
        config.browser == "firefox"            # env перекрывает TOML
        config.generation_attempts == 5        # str→int коэрсия
        config.cache_root == str(tmp_path / ".prettyplay" / "cache")
        ```
      - `test_load_config_no_pyproject_fails_loudly` — Setup: изолированный рабочий каталог
        без pyproject.toml вверх по дереву (`monkeypatch.chdir(tmp_path)`; при
        недетерминированности окружения — `mock.patch` поиска вверх от cwd).
        Input: `load_config(pyproject_path=None)`.
        Assertions: `pytest.raises` с текстом `"pyproject.toml not found"`
      - `test_load_config_missing_section_yields_defaults` — Setup: `tmp_path/pyproject.toml`
        без `[tool.prettyplay]` (например, только `[project]`).
        Assertions: `config.provider == "openai"; config.generation_attempts == 3`
- [x] **Debugging**: `.venv/bin/pytest tests/config/ -x` — исправлять реализацию, пока не зелено
- [x] **Contract re-verification**: фасад клетки config полон (`Config`, `load_config`);
      «never read LLM API keys from any file» — в функции нет чтения чего-либо, кроме TOML
- [x] **Lint**: `.venv/bin/ruff check prettyplay/config/ tests/config/`
- [x] Клетка config завершена: `goga lint` — 0 ошибок; фасад-проверка:
      `.venv/bin/python -c "from prettyplay.config import Config, load_config"`

### Task 4: `StepHooks` + `StepReporter` — видимость (prettyplay/reporting/{hooks,reporter}.py)

Контекст: две сущности клетки `prettyplay/reporting`. `StepHooks` (`location: hooks.py`) —
база callback-контракта с 8 no-op методами. `StepReporter` (`location: reporter.py`) — единая
точка видимости: `__init__(hooks: list[StepHooks])` сохраняет список по ссылке в публичный
атрибут `self.hooks`; метод `emit(event, payload)` пишет логгеру `logging.getLogger("prettyplay")`
и делает синхронный fan-out на хуки. Фасад: `from prettyplay.reporting import StepHooks,
StepReporter` (создать `__init__.py`). Клетка reporting завершается этой задачей.
Связь с `hooks.md` из Imports не нужна — это клетки-потребители.

**Usages relevant to this task:**
- `conventions`: logging — `logging.getLogger("prettyplay")`, контекст через `extra`,
  lowercase-сообщения, уровни INFO/WARNING; Google-docstring.
- `hooks` (imported usage, для понимания контракта payload): значения — строки, счётчик
  попытки — int.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm `StepReporter` (verbatim из дизайна):
```
1. __init__(hooks: list[StepHooks]) — сохраняет список по ссылке в публичный атрибут
   self.hooks (add_hooks у PrettyTest аппендит в этот же список)
2. emit(event, payload):
   a. level = WARNING if event in {"on_cache_skipped"} else INFO
      (сбой хука логируется отдельно WARNING)
   b. extra = {("ctx_" + key) if key in _LOG_RECORD_RESERVED else key: value
      for key, value in payload.items()}; logger.log(level, event, extra=extra)
      (_LOG_RECORD_RESERVED — замороженное множество зарезервированных атрибутов LogRecord:
      name, msg, message, args, levelname, levelno, pathname, filename, module, exc_info,
      funcName, lineno, created, msecs, relativeCreated, thread, threadName, process,
      processName, stack_info, asctime, taskName; санитизация касается только лог-записи —
      иначе Logger.makeRecord бросает KeyError «Attempt to overwrite … in LogRecord»;
      ключ `filename` события on_cache_saved логируется как ctx_filename)
   c. FOR hook in self.hooks (порядок регистрации):
        try: getattr(hook, event)(**payload)
        except Exception: logger.warning("hook call failed", extra={"event": event,
              "hook": type(hook).__name__})
```

Методы `StepHooks` (8, тела `pass`): `on_step_started(step_text, step_type)`,
`on_step_passed(step_text, step_type)`, `on_step_failed(step_text, step_type, error)`,
`on_generation_started(step_text, attempt)`, `on_healing_started(step_text, category)`,
`on_healed(step_text, explanation)`, `on_cache_saved(step_text, filename)`,
`on_cache_skipped(step_text, reason)`.

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 4 — StepHooks + StepReporter
- [x] **Contract tests** (`tests/reporting/test_hooks.py`, `tests/reporting/test_reporter.py`):
      `from prettyplay.reporting import StepHooks, StepReporter`; у `StepHooks` существуют
      все 8 методов с точными сигнатурами (проверка через `inspect.signature`); вызов каждого
      no-op метода базового класса не падает; `StepReporter(hooks=[])` конструируется;
      `reporter.hooks` — публичный список. Ожидаемый провал
- [x] **Code**: создать `prettyplay/reporting/hooks.py` (класс `StepHooks`, 8 no-op методов)
- [x] **Code**: создать `prettyplay/reporting/reporter.py` (класс `StepReporter`,
      `_LOG_RECORD_RESERVED: frozenset[str]`, метод `emit`) по алгоритму выше
- [x] **Code**: создать `prettyplay/reporting/__init__.py` — `from .hooks import StepHooks`,
      `from .reporter import StepReporter`, `__all__ = ["StepHooks", "StepReporter"]`
- [x] **Interface verification**: `.venv/bin/pytest tests/reporting/ -v`; фасад:
      `.venv/bin/python -c "from prettyplay.reporting import StepHooks, StepReporter"`
- [x] **Logic tests**:
      - `test_emit_dispatches_event_to_hooks_in_order` (`tests/reporting/test_reporter.py`) —
        Setup: два хука-рекордера `RecordingHook(StepHooks)` с общим списком `calls`;
        reporter = `StepReporter(hooks=[h1, h2])`.
        Input: `reporter.emit("on_step_started", {"step_text": "открыть страницу", "step_type": "action"})`.
        Assertions (verbatim):
        ```
        calls == [("h1", "on_step_started", "открыть страницу", "action"),
                  ("h2", "on_step_started", "открыть страницу", "action")]
        caplog: одна запись INFO, logger == "prettyplay", msg == "on_step_started",
                record.step_text == "открыть страницу"
        ```
      - `test_raising_hook_is_skipped_and_logged` — Setup: h1 — хук, бросающий RuntimeError
        на on_step_passed; h2 — рекордер; `caplog`.
        Input: `reporter.emit("on_step_passed", {"step_text": "s", "step_type": "action"})`.
        Assertions (verbatim):
        ```
        исключение не пробросилось наружу
        h2 получил событие
        в caplog есть WARNING от логгера "prettyplay"
        ```
      - дополнительный edge (санитизация, из R1 дизайна): `emit("on_cache_saved",
        {"step_text": "s", "filename": "abc.py"})` не бросает KeyError; в caplog запись имеет
        атрибут `ctx_filename == "abc.py"`; хук получил оригинальный kwarg `filename`
      - дополнительный edge: пустой список хуков — только логирование; `on_cache_skipped`
        логируется уровнем WARNING
- [x] **Debugging**: `.venv/bin/pytest tests/reporting/ -x`
- [x] **Contract re-verification**: 8 методов = 8 событий один-в-один; уровни INFO/WARNING;
      хуки получают оригинальные kwargs; синхронный fan-out
- [x] **Lint**: `.venv/bin/ruff check prettyplay/reporting/ tests/reporting/`
- [x] Клетка reporting завершена: `goga lint` — 0 ошибок; фасад-проверка импорта

### Task 5: Таксономия сбоев (prettyplay/failures/errors.py)

Контекст: четыре контрактные сущности клетки `prettyplay/failures` в одном `location: errors.py`
(группировка по location): база `PrettyplayError(message)` и три мутации `PrettyplayError::`
— `ProductDefectError(step_text, message)`, `IncurableStepError(step_text, reason,
recommendation)`, `LlmUnavailableError(message)`. Все ловятся одним
`except PrettyplayError`. Поля сохраняются как атрибуты (properties из CODEMANIFEST).
`IncurableStepError.__str__` рендерит все три поля. Фасад: `from prettyplay.failures import
PrettyplayError, ProductDefectError, IncurableStepError, LlmUnavailableError`.
Клетка failures завершается этой задачей.

**Usages relevant to this task:**
- `conventions`: docstrings, type hints.
- `taxonomy` (imported usage, клетки-потребители): поле `recommendation` читается
  потребителями как `info.value.recommendation` — атрибут обязателен.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. PrettyplayError(Exception): __init__(message) → self.message = message
2. ProductDefectError(PrettyplayError): __init__(step_text, message) → оба атрибута;
   str = f"product defect on step {step_text!r}: {message}"
3. IncurableStepError(PrettyplayError): __init__(step_text, reason, recommendation) →
   три атрибута; str включает все три поля
4. LlmUnavailableError(PrettyplayError): __init__(message) → атрибут message
```

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 5 — таксономия сбоев
- [x] **Contract tests** (`tests/failures/test_errors.py`): все четыре имени импортируются из
      `prettyplay.failures`; каждая мутация — подкласс `PrettyplayError`; у
      `ProductDefectError` свойства `step_text`/`message`; у `IncurableStepError` —
      `step_text`/`reason`/`recommendation`; у `LlmUnavailableError` — `message`.
      Ожидаемый провал
- [x] **Code**: создать `prettyplay/failures/errors.py` по алгоритму выше
- [x] **Code**: создать `prettyplay/failures/__init__.py` с реэкспортом всех четырёх имён
      и `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/failures/test_errors.py -v`; фасад:
      `.venv/bin/python -c "from prettyplay.failures import PrettyplayError, ProductDefectError, IncurableStepError, LlmUnavailableError"`
- [x] **Logic tests**:
      - `test_incurable_error_message_renders_all_fields` —
        Input: `str(IncurableStepError("шаг", "причина", "рекомендация"))`.
        Assertions (verbatim):
        ```
        "шаг" in s and "причина" in s and "рекомендация" in s
        ошибка — экземпляр PrettyplayError (единый except на границе suite)
        ```
      - дополнительный positive: `ProductDefectError("шаг", "ожидание не оправдалось")`
        — `str()` содержит шаг и сообщение; `LlmUnavailableError("llm unavailable: openai:
        ...")` — `message` доступен; каждая — `issubclass(..., PrettyplayError)`
- [x] **Debugging**: `.venv/bin/pytest tests/failures/ -x`
- [x] **Contract re-verification**: три различимых вида, один базовый except; поля-атрибуты
      соответствуют properties контракта
- [x] **Lint**: `.venv/bin/ruff check prettyplay/failures/ tests/failures/`
- [x] Клетка failures завершена: `goga lint` — 0 ошибок; фасад-проверка импорта

### Task 6: `DriverSession` — жизненный цикл браузера (prettyplay/driver/session.py)

Контекст: сущность клетки `prettyplay/driver`, `location: session.py`. Владелец Playwright
sync-драйвера и браузера на прогон. Imports: `Config` from `prettyplay/config` — канонический
фасадный относительный импорт `from ..config import Config`. Конструктор ничего не запускает;
`open_context()` лениво стартует `sync_playwright().start()` (сессия живёт весь прогон — явный
start, не with-блок), запускает браузер через словарь движков `{chromium, firefox, webkit}`
ровно один раз, затем `browser.new_context()` → `context.new_page()` → `PageFacade(page,
context)`. `close()` — `browser.close()` + `playwright.stop()` + обнуление полей; безопасен
при незапуске (no-op). Ошибки Playwright пробрасываются как есть. Фасад: DriverSession.

**Usages relevant to this task:**
- `playwright`: sync lifecycle — `sync_playwright().start()` для долгоживущей сессии;
  словарь `{"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}` →
  `.launch()`; headless по умолчанию.
- `conventions`: моки внешних зависимостей — `mock.patch` на `prettyplay.driver.session.sync_playwright`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. __init__(config): self._config, self._playwright=None, self._browser=None
2. open_context():
   IF self._browser is None:
     self._playwright = sync_playwright().start()
     engines = {"chromium": self._playwright.chromium, "firefox": self._playwright.firefox,
                "webkit": self._playwright.webkit}
     self._browser = engines[self._config.browser].launch()
   context = self._browser.new_context(); page = context.new_page()
   RETURN PageFacade(page, context)
3. close(): IF self._browser: self._browser.close(); self._playwright.stop();
   обнулить оба поля (идемпотентно, безопасно при незапуске)
```

Примечание: `PageFacade` ещё не реализован (Задача 7). Для независимости задач: в этой задаче
`open_context` возвращает `PageFacade(...)`, импортированный из `.page`; чтобы задача была
исполнимой, создайте в `prettyplay/driver/page.py` минимальный скелет `PageFacade.__init__(page,
context)` (без методов — полная реализация в Задаче 7), либо реализуйте Задачи 6 и 7 в одном
сеансе, сохраняя порядок чекбоксов. Контрактные тесты Задачи 6 мокают `sync_playwright`.

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 6 — DriverSession
- [x] **Contract tests** (`tests/driver/test_session.py`): `from prettyplay.driver import
      DriverSession`; `DriverSession(config)` конструируется без запуска чего-либо;
      `open_context() -> PageFacade`; `close()` без запуска не падает. Ожидаемый провал
- [x] **Code**: создать `prettyplay/driver/session.py` по алгоритму выше (скелет `page.py`
      при необходимости — см. примечание)
- [x] **Code**: создать/дополнить `prettyplay/driver/__init__.py` — реэкспорт `DriverSession`
- [x] **Interface verification**: `.venv/bin/pytest tests/driver/test_session.py -v`
- [x] **Logic tests**:
      - `test_open_context_lazy_launch_single_browser` — Setup: `mock.patch(
        "prettyplay.driver.session.sync_playwright")` → fake pw: `pw().start()` возвращает
        объект с `chromium/firefox/webkit`, каждый `.launch()` пишет в `launches`;
        `new_context()` → контекст с `new_page()`.
        Input: `session = DriverSession(Config(browser="chromium"))`; `session.open_context()` ×2.
        Assertions (verbatim):
        ```
        после конструктора: pw.start не вызывался
        launches == 1
        два результата — разные PageFacade; контекстов создано 2
        ```
      - дополнительный edge: повторный `close()` — no-op; `close()` до запуска — no-op
- [x] **Debugging**: `.venv/bin/pytest tests/driver/test_session.py -x`
- [x] **Contract re-verification**: один браузер на прогон; изолированный контекст на вызов;
      ленивость конструктора
- [x] **Lint**: `.venv/bin/ruff check prettyplay/driver/ tests/driver/`

### Task 7: `PageFacade` + `LocatorFacade` — фасад страницы (prettyplay/driver/page.py)

Контекст: две сущности одного `location: page.py` клетки driver. Узкий стабильный фасад —
единственная страница-API сгенерированного кода; backward-compatibility контракт (расширять,
никогда не переименовывать/удалять). Никаких `time.sleep`; ожидания — только через
`playwright.sync_api.expect`; наружу не отдаётся ни один сырой объект Playwright (возвраты —
str / bytes / LocatorFacade). Клетка driver завершается этой задачей. Поверхность этого
фасада — источник `PAGE_API_SURFACE` для Задачи 16 (генератор).

**Usages relevant to this task:**
- `playwright`: локаторы `get_by_role(role, name=name)` / `get_by_label` / `get_by_text`;
  `page.locator("body").aria_snapshot()`; `page.screenshot(full_page=True)`;
  `expect(locator).to_be_visible()/to_contain_text()/to_be_enabled()`; auto-wait.
- `facade` (imported usage): `.usages/facade.md` описывает поверхность для потребителей —
  реализация обязана ему соответствовать.
- `conventions`: мок Playwright на внешней границе.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
PageFacade.__init__(page, context) — приватные поля
  open(url)            → self._page.goto(url)
  find_by_role(r, name)→ LocatorFacade(self._page.get_by_role(r, name=name))
  find_by_label(l)     → LocatorFacade(self._page.get_by_label(l))
  find_by_text(t)      → LocatorFacade(self._page.get_by_text(t))
  aria_snapshot()      → self._page.locator("body").aria_snapshot()
  screenshot()         → self._page.screenshot(full_page=True)  # bytes
  url (property)       → self._page.url
  close()              → self._context.close()

LocatorFacade.__init__(locator)
  click()              → self._locator.click()
  fill(value)          → self._locator.fill(value)
  select_option(value) → self._locator.select_option(value)
  expect_visible()     → expect(self._locator).to_be_visible()
  expect_text(text)    → expect(self._locator).to_contain_text(text)
  expect_enabled()     → expect(self._locator).to_be_enabled()
```

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 7 — PageFacade + LocatorFacade
- [x] **Contract tests** (`tests/driver/test_page.py`): `from prettyplay.driver import
      PageFacade, LocatorFacade`; полный набор методов/свойств по контракту (7 методов + url
      у PageFacade; 6 методов у LocatorFacade); сигнатуры (`find_by_role(role: str, name: str)`,
      `fill(value: str)` и т.д.). Ожидаемый провал
- [x] **Code**: дополнить `prettyplay/driver/page.py` полной реализацией обоих фасадов
- [x] **Code**: `prettyplay/driver/__init__.py` — полный реэкспорт клетки:
      `DriverSession`, `PageFacade`, `LocatorFacade` + `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/driver/ -v`
- [x] **Logic tests** (`tests/driver/test_page.py`, fake-playwright-объекты с записью вызовов —
      моки только на границе):
      - делегирование каждого метода PageFacade (`open` → `page.goto(url)`; локаторы →
        соответствующие вызовы с возвратом `LocatorFacade`; `aria_snapshot` →
        `page.locator("body").aria_snapshot()`; `screenshot` → `page.screenshot(full_page=True)`
        возвращает bytes; `url` → `page.url`; `close` → `context.close()`)
      - делегирование каждого метода LocatorFacade (`click`, `fill`, `select_option`,
        `expect_visible`/`expect_text`/`expect_enabled` → `expect(locator).to_*` — мок
        `playwright.sync_api.expect` или инъекция)
      - edge: неуспешное ожидание бросает AssertionError (идёт в классификацию); никакой
        метод не возвращает сырой объект Playwright
- [x] **Debugging**: `.venv/bin/pytest tests/driver/ -x`
- [x] **Contract re-verification**: поверхность = контрактной (расширение запрещено переименованием);
      никаких фиксированных задержек в коде
- [x] **Lint**: `.venv/bin/ruff check prettyplay/driver/ tests/driver/`
- [x] Клетка driver завершена: `goga lint` — 0 ошибок; фасад-проверка:
      `.venv/bin/python -c "from prettyplay.driver import DriverSession, PageFacade, LocatorFacade"`

### Task 8: `normalize_step_text` — нормализация предложения (prettyplay/cache/text.py)

Контекст: Routine клетки `prettyplay/cache`, `location: text.py`. Чистая функция адресации:
NFC → strip → collapse → casefold. Без I/O и локали. Первая задача клетки cache.

**Usages relevant to this task:**
- `conventions`: чистая логика — тесты без моков; docstring.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. s = unicodedata.normalize("NFC", text)
2. s = s.strip()
3. s = re.sub(r"\s+", " ", s)
4. RETURN s.casefold()
```

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 8 — normalize_step_text
- [x] **Contract tests** (`tests/cache/test_text.py`): `from prettyplay.cache import
      normalize_step_text`; сигнатура `(text: str) -> str`. Ожидаемый провал
- [x] **Code**: создать `prettyplay/cache/text.py`; создать `prettyplay/cache/__init__.py`
      с реэкспортом `normalize_step_text`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/test_text.py -v`; фасад:
      `.venv/bin/python -c "from prettyplay.cache import normalize_step_text"`
- [x] **Logic tests**:
      - `test_normalize_step_text_equivalence` — Input: `normalize_step_text("  Нажать   Войти ")`,
        `normalize_step_text("нажать войти")`.
        Assertions (verbatim):
        ```
        normalize_step_text("  Нажать   Войти ") == normalize_step_text("нажать войти") == "нажать войти"
        normalize_step_text("Нажать Войти") != normalize_step_text("Click Login")
        ```
      - `test_normalize_empty_and_whitespace_only` — Input: `normalize_step_text("")`,
        `normalize_step_text("   ")`, `normalize_step_text("\n\t")`.
        Assertions: все три → `""`
- [x] **Debugging**: `.venv/bin/pytest tests/cache/test_text.py -x`
- [x] **Contract re-verification**: чистая функция; пайплайн NFC→strip→collapse→casefold
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`

### Task 9: `StepIdentity` + `CachedStep` — модели кэша (prettyplay/cache/models.py)

Контекст: две сущности одного `location: models.py` клетки cache. `StepIdentity` — адрес шага:
тройка (cache_key, step_type, normalized_text) + вычисляемое `filename`. `CachedStep` —
единица кэша в памяти. Обе модели — pydantic v2 kw_only; поля тройки/кэша семантически
обязательны, дефолтов не имеют (kw_only-конструкция обязательна);
`filename` — `cached_property` (или обычное property) поверх тройки. Разделитель `\x1f`
(Unit Separator) делает конкатенацию однозначной.

**Usages relevant to this task:**
- `pydantic`: kw_only-модели.
- `conventions`: модели pydantic; `None` только для явной отсутствующности.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
StepIdentity (BaseModel, kw_only): cache_key: str, step_type: str, normalized_text: str
  filename (cached_property):
    identity_string = "\x1f".join((cache_key, step_type, normalized_text))
    RETURN hashlib.sha256(identity_string.encode("utf-8")).hexdigest() + ".py"

CachedStep (BaseModel, kw_only): identity: StepIdentity, code: str, created_at: str
```

Чекпойнт трассировки: имя файла не обязано быть python-идентификатором (hex-дайджест может
начинаться с цифры) — load разбирает текст файла, import по имени не выполняется;
детерминизм и различимость троек (sha256).

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 9 — StepIdentity + CachedStep
- [x] **Contract tests** (`tests/cache/test_models.py`): оба имени из `prettyplay.cache`;
      kw_only-конструкция (позиционная → TypeError); свойства `cache_key`/`step_type`/
      `normalized_text`/`filename` у StepIdentity; `identity`/`code`/`created_at` у CachedStep.
      Ожидаемый провал
- [x] **Code**: создать `prettyplay/cache/models.py` по алгоритму выше
- [x] **Code**: `prettyplay/cache/__init__.py` — добавить `StepIdentity`, `CachedStep`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/test_models.py -v`
- [x] **Logic tests**:
      - `test_identity_filename_deterministic_and_discriminating` — Input: две идентичные и
        две различающиеся тройки.
        Trace (verbatim):
        ```
        StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename
        StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename   # тот же digest
        StepIdentity(cache_key="k", step_type="assertion", normalized_text="нажать войти").filename # другой digest
        StepIdentity(cache_key="k2", step_type="action", normalized_text="нажать войти").filename   # другой digest
        ```
        Assertions (verbatim):
        ```
        f1 == f2; f1 != f3; f1 != f4
        f1.endswith(".py") and len(digest-часть) == 64
        ```
- [x] **Debugging**: `.venv/bin/pytest tests/cache/ -x`
- [x] **Contract re-verification**: filename — детерминированная функция тройки
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`

### Task 10: `StepCache` — репозиторий шагов (prettyplay/cache/store.py)

Контекст: сущность клетки cache, `location: store.py`. Imports: `Config` from
`prettyplay/config`; `StepReporter` + usages `hooks` from `prettyplay/reporting`
(события записи кэша). Свойства `root` (str) и `writable` (ленивая проверка). `load` —
всегда читается, любая структурная ошибка = защитный промах None. `save` — атомарная
best-effort запись (tmp + os.replace), read-only → тихо-громкий skip с WARNING-событием.
Использует `StepIdentity`/`CachedStep` из `.models`, `StepReporter` для emit.

**Usages relevant to this task:**
- `hooks` (from `prettyplay/reporting`): payload событий `on_cache_saved(step_text,
  filename)` / `on_cache_skipped(step_text, reason)` — строки.
- `conventions`: файловые тесты — только `tmp_path`; caplog для проверки логгера.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. __init__(config, path, reporter):
   self._root = Path(config.cache_root)  # уже абсолютный после load_config
   self._subdir = Path(path) if path else None   # часть адреса
   self._reporter = reporter; self._writable = None (лениво)
2. root (property) → str(self._root)
3. writable (property):
   IF self._writable is None:
     try: self._target_dir().mkdir(parents=True, exist_ok=True)
          self._writable = os.access(self._target_dir(), os.W_OK)
     except OSError: self._writable = False
   RETURN self._writable
4. load(identity):
   target = self._target_dir() / identity.filename
   IF not target.exists(): RETURN None
   TRY (защитный блок разбора — любая структурная ошибка = промах, а не сбой прогона):
     text = target.read_text(encoding="utf-8")
     parse header: STEP_TEXT / CACHE_KEY / STEP_TYPE / CREATED_AT = <literal> (ast.literal_eval)
     code = text с первого вхождения "def step(" (поиск по "\ndef step(", но ведущий
     перевод строки в код НЕ входит — loaded.code.startswith("def step(") детерминированно
     выполняется; отсутствие "def step(" — структурная ошибка → защитный промах)
     IF (CACHE_KEY, STEP_TYPE) != (identity.cache_key, identity.step_type)
        или STEP_TEXT != identity.normalized_text: RETURN None   # защитный промах
     RETURN CachedStep(identity=identity, code=code, created_at=CREATED_AT)
   EXCEPT (ValueError, SyntaxError, KeyError, IndexError, OSError): RETURN None
   # невалидный заголовок/литерал, отсутствие любого поля метаданных или хвоста def step(,
   # нечитаемый файл — повреждение кэша никогда не калечит прогон
   # (контракт: «The cache is always read»)
5. save(step):
   IF not self.writable:
     emit on_cache_skipped(step_text=normalized, reason="read-only cache"); RETURN
   body = header-константы (repr-значения) + "\n\n" + step.code + "\n"
   tmp = tempfile.mkstemp(dir=self._target_dir(), prefix=".tmp-", suffix=".py")
   write body; fsync; close
   FOR attempt in 1..3: try os.replace(tmp, target); BREAK
     except PermissionError: time.sleep(0.1)   # Windows: цель занята
   ELSE: удалить tmp; emit on_cache_skipped(reason="cache target busy"); RETURN
   emit on_cache_saved(step_text=normalized, filename=identity.filename)
```

Примечание: `time.sleep(0.1)` в цикле replace — единственный разрешённый библиотечный
бэкофф (Windows), не страничное ожидание.

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 10 — StepCache
- [x] **Contract tests** (`tests/cache/test_store.py`): `from prettyplay.cache import
      StepCache`; сигнатура `StepCache(config, path, reporter)` (path опционален); свойства
      `root -> str`, `writable -> bool`; методы `load(identity)` / `save(step)`.
      Ожидаемый провал
- [x] **Code**: создать `prettyplay/cache/store.py` по алгоритму выше
- [x] **Code**: `prettyplay/cache/__init__.py` — добавить `StepCache`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/test_store.py -v`
- [x] **Logic tests**:
      - `test_save_load_roundtrip_via_file` — Setup: `tmp_path`; `Config(cache_root=str(tmp_path))`;
        reporter с рекордером; `cache = StepCache(config, "checkout", reporter)`;
        `identity = StepIdentity(cache_key="login-flow", step_type="action",
        normalized_text="открыть страницу логина")`.
        Input: `cache.save(CachedStep(identity=identity, code="def step(page) -> None:\n    page.open('https://x')\n", created_at="2026-09-07"))`;
        затем `cache.load(identity)`.
        Assertions (verbatim):
        ```
        loaded is not None
        loaded.identity == identity
        loaded.code.startswith("def step(")
        loaded.created_at == "2026-09-07"
        файл: text.startswith("STEP_TEXT =") и "def step(" in text
        recorded: ("on_cache_saved", {"filename": identity.filename})
        caplog: запись INFO "on_cache_saved" от логгера "prettyplay"; record.ctx_filename == identity.filename
        import файла через importlib.util.spec_from_file_location("cached_step", path)
          + module_from_spec + exec_module успешен (валидный модуль; имя файла-дайджеста
          не обязано быть идентификатором — load идёт текстом, не по имени модуля)
        ```
      - `test_save_readonly_cache_skips_loudly` — Setup: `tmp_path`-каталог, `chmod 0o500`
        (skipif если запуск под root — root игнорирует режимы); рекордер событий.
        Assertions (verbatim):
        ```
        исключений нет; файл не создан
        recorded: ("on_cache_skipped", reason="read-only cache")
        ```
      - `test_load_missing_file_returns_none` — Input: `cache.load(StepIdentity(cache_key="k",
        step_type="action", normalized_text="нет такого шага"))`. Assertions: `result is None`
      - `test_load_metadata_mismatch_treated_as_miss` — Setup: в `tmp_path`-кэше файл с
        digest'ом identity, но вручную изменённым `STEP_TEXT`. Assertions: `result is None`
        (шаг будет регенерирован, прогон не падает)
      - `test_load_corrupt_file_treated_as_miss` — Setup: в `tmp_path`-кэше файл с именем
        `identity.filename`, содержимое — обрывок без заголовка и без `def step(`:
        `"garbage not a module"`. Assertions: `result is None` (без исключений)
- [x] **Debugging**: `.venv/bin/pytest tests/cache/ -x`
- [x] **Contract re-verification**: чтение всегда работает; ни одна ошибка записи не роняет
      прогон; конкурентные писатели — последний побеждает (атомарный replace)
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`

### Task 11: `RunBudgets` — реестр попыток (prettyplay/cache/budgets.py)

Контекст: сущность клетки cache, `location: budgets.py`. Per-run реестр: сколько попыток
генерации/лечения осталось шагу в рамках прогона. Ключ — `identity.filename: str`
(детерминированный, без коллизий; pydantic-модели по умолчанию нехешируемы — строковый ключ
проще и надёжнее). Раздельные словари gen/heal. Ничего не персистируется; бюджеты не
сбрасываются между тестами. Клетка cache завершается этой задачей.

**Usages relevant to this task:**
- `conventions`: чистая логика — без моков.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. __init__(generation_limit, healing_limit): два dict[str, int] (ключ = identity.filename)
2. try_generation(identity):
   used = self._gen.get(key, 0)
   IF used >= self._generation_limit: RETURN False
   self._gen[key] = used + 1; RETURN True
3. try_healing — симметрично с self._heal / self._healing_limit
```

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 11 — RunBudgets
- [x] **Contract tests** (`tests/cache/test_budgets.py`): `from prettyplay.cache import
      RunBudgets`; сигнатура `RunBudgets(generation_limit, healing_limit)`; методы
      `try_generation(identity) -> bool`, `try_healing(identity) -> bool`. Ожидаемый провал
- [x] **Code**: создать `prettyplay/cache/budgets.py` по алгоритму выше
- [x] **Code**: `prettyplay/cache/__init__.py` — полный фасад клетки:
      `normalize_step_text`, `StepIdentity`, `CachedStep`, `StepCache`, `RunBudgets` + `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/ -v`
- [x] **Logic tests**:
      - `test_budgets_separate_pools_shared_per_identity` — Setup:
        `budgets = RunBudgets(generation_limit=1, healing_limit=1)`; `identity` и `identity2`.
        Input: `try_generation(identity)` ×2; `try_healing(identity)`; `try_generation(identity2)`.
        Assertions (verbatim): `результаты: [True, False, True, True]`
      - `test_budgets_default_limits_from_config` — Input:
        `RunBudgets(config.generation_attempts, config.healing_attempts)` при `Config()`.
        Assertions (verbatim):
        ```
        [try_generation(id) for _ in range(4)] == [True, True, True, False]
        [try_healing(id) for _ in range(3)] == [True, True, False]
        ```
- [x] **Debugging**: `.venv/bin/pytest tests/cache/ -x`
- [x] **Contract re-verification**: один реестр на процесс; раздельные лимиты; False на исчерпание
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`
- [x] Клетка cache завершена: `goga lint` — 0 ошибок; фасад-проверка:
      `.venv/bin/python -c "from prettyplay.cache import StepCache"`

### Task 12: `FailureClassification` — вердикт классификации (prettyplay/llm/models.py)

Контекст: сущность клетки `prettyplay/llm`, `location: models.py`. Модель вердикта: категория
(одна из rot / product_defect / incurable), объяснение, рекомендация. pydantic v2 kw_only.
Первая задача клетки llm.

**Usages relevant to this task:**
- `pydantic`: kw_only-модели.
- `classification` (imported usage, для потребителя — healer): категории решения лечения.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 12 — FailureClassification
- [x] **Contract tests** (`tests/llm/test_models.py`): `from prettyplay.llm import
      FailureClassification`; kw_only; свойства `category`/`explanation`/`recommendation` (str).
      Ожидаемый провал
- [x] **Code**: создать `prettyplay/llm/models.py` (модель) и `prettyplay/llm/__init__.py`
      с реэкспортом `FailureClassification`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/test_models.py -v`
- [x] **Logic tests**: positive — `FailureClassification(category="rot", explanation="e",
      recommendation="r")` хранит все три; edge — категории всех трёх допустимых значений
      конструируются
- [x] **Debugging**: `.venv/bin/pytest tests/llm/test_models.py -x`
- [x] **Contract re-verification**: три свойства; категория — строка-ярлык
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`

### Task 13: `LlmProvider` (порт) + `create_provider` (prettyplay/llm/provider.py)

Контекст: две сущности одного `location: provider.py` клетки llm. `LlmProvider` — единый
LLM-порт: методы `generate_step_code(prompt, step_text, previous_steps, snapshot, screenshot,
page_api, existing_code, error) -> str` и `classify_failure(prompt, step_text, code, error,
snapshot, screenshot) -> FailureClassification`. Реализации — мутации в отдельных файлах
(Задачи 14–15); сам порт — базовый класс с этими сигнатурами (тела — поднятие
NotImplementedError; порт не инстанцируется в рантайме). `create_provider(config)` —
фабрика по `config.provider`. Imports: `Config` from `prettyplay/config`, `LlmUnavailableError`
from `prettyplay/failures`, `FailureClassification` из `.models`.

**Usages relevant to this task:**
- `conventions`: type hints обязательны; docstrings.
- `taxonomy`: `LlmUnavailableError` — единственный вид сбоя провайдера.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm `create_provider` (verbatim из дизайна):
```
IF config.provider == "openai":    RETURN OpenAiProvider(config)
ELIF config.provider == "anthropic": RETURN AnthropicProvider(config)
ELSE: raise ValueError("unsupported provider {config.provider!r}: expected one of openai, anthropic")
```

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 13 — LlmProvider + create_provider
- [x] **Contract tests** (`tests/llm/test_provider.py`): `from prettyplay.llm import
      LlmProvider, create_provider`; у порта методы `generate_step_code` и `classify_failure`
      с точными сигнатурами (inspect); `create_provider` — вызываем с Config.
      Ожидаемый провал
- [x] **Code**: создать `prettyplay/llm/provider.py`: класс `LlmProvider` (порт) и функцию
      `create_provider` с обеими ветками ("openai" → OpenAiProvider, "anthropic" →
      AnthropicProvider, иное — ValueError по алгоритму). Для исполнимости задачи в одном
      сеансе (паттерн Задачи 6): создать минимальные скелеты `OpenAiProvider(LlmProvider)` и
      `AnthropicProvider(LlmProvider)` в `prettyplay/llm/openai_provider.py` и
      `prettyplay/llm/anthropic_provider.py` (скелет: конструктор `__init__(config)` сохраняет
      config в приватное поле; методы порта наследуются от `LlmProvider`; полная реализация —
      Задачи 14–15), чтобы `create_provider` возвращал реальные инстансы и все тесты Задачи 13
      проходили
- [x] **Code**: `prettyplay/llm/__init__.py` — добавить `LlmProvider`, `create_provider`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/test_provider.py -v`
- [x] **Logic tests**:
      - `test_create_provider_selects_by_config` — Setup: `Config(provider="anthropic",
        model="claude-sonnet-4-5")` (env-ключей нет — не нужен).
        Input: `create_provider(config)`.
        Assertions (verbatim):
        ```
        isinstance(provider, AnthropicProvider)
        isinstance(provider, LlmProvider)   # контракт порта
        ```
        (плюс симметричный случай `provider="openai"` → OpenAiProvider)
      - `test_create_provider_unknown_fails_loudly` — Input:
        ```python
        config = Config.model_construct(provider="groq")  # валидация обойдена намеренно:
                                                          # Literal иначе не пропустит значение
        create_provider(config)
        ```
        Assertions (verbatim): `pytest.raises(ValueError)`; `"openai"` и `"anthropic"` в тексте
- [x] **Debugging**: `.venv/bin/pytest tests/llm/ -x`
- [x] **Contract re-verification**: двойная защита (Literal в Config + ValueError в фабрике);
      один запрос на попытку — у порта нет своих ретраев
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`

### Task 14: `OpenAiProvider` (prettyplay/llm/openai_provider.py)

Контекст: мутация `LlmProvider::OpenAiProvider(config)`, `location: openai_provider.py`.
Ленивый клиент: конструктор НЕ читает env (старт без кредов); при первом запросе
`os.environ.get("OPENAI_API_KEY")` — отсутствие/пустота → `LlmUnavailableError` с именем
провайдера и переменной; `config.base_url` непуст → передаётся в конструктор клиента.
`generate_step_code`: `client.chat.completions.create(model=config.effective_generation_model,
messages=[{"role":"system","content":prompt}, {"role":"user","content":user_content}])`;
user_content — текстовый блок с полями STEP / PREVIOUS STEPS / PAGE SNAPSHOT / PAGE API /
CODE / ERROR (последние два — только регенерационные запросы); при `screenshot is not None` —
список блоков `[{"type":"text","text":...}, {"type":"image_url","image_url":{"url":
"data:image/png;base64,..."}}]`. `classify_failure`: один запрос (модель
`effective_classification_model`), ответ — одна строка `category | explanation |
recommendation`; парсинг: strip → первая непустая строка → split `"|"` на 3 части → strip
каждой; категория ∈ {rot, product_defect, incurable}; непарсимый/неизвестный вердикт →
защитный маппинг в incurable. Ошибки SDK (`openai.OpenAIError`) → `LlmUnavailableError
("llm unavailable: openai request failed") from error`. Prompt передаётся verbatim.

**Usages relevant to this task:**
- `openai`: `OpenAI(api_key=os.environ["OPENAI_API_KEY"])`; `chat.completions.create`;
  `response.choices[0].message.content`; `OpenAIError` — база ошибок SDK.
- `conventions`: моки SDK на внешней границе (`mock.patch` клиента).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Каркас (общий для обоих провайдеров, verbatim из дизайна):
```
1. __init__(config): self._config; self._client = None
2. _get_client() (лениво):
   key = os.environ.get("OPENAI_API_KEY")
   IF not key: raise LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")
   construct SDK client (api_key=key; base_url=config.base_url or None)
3. generate_step_code(...):
   model = config.effective_generation_model
   messages: system=prompt (verbatim), user=build_user_content(...)
   send ONE request; extract text; RETURN code
4. classify_failure(...):
   model = config.effective_classification_model
   send ONE request; parse "category | explanation | recommendation"
   IF парсинг не удался или категория неизвестна:
     RETURN FailureClassification("incurable", "classification verdict unparsable",
                                  "re-run the step or check the provider answer")
   RETURN FailureClassification(category, explanation, recommendation)
5. Обёртка запросов: except openai.OpenAIError as e:
   raise LlmUnavailableError("llm unavailable: openai request failed") from e
```

`build_user_content` — единый для обоих провайдеров формат полей; мультимодальная разница —
только в обёртке контент-блоков каждого SDK. Разумно вынести общий хелпер построения полей
во внутренний модуль клетки (например, `_request.py`) — допустимая внутренняя декомпозиция.

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 14 — OpenAiProvider
- [x] **Contract tests** (`tests/llm/test_openai_provider.py`): `from prettyplay.llm import
      OpenAiProvider`; `isinstance(OpenAiProvider(Config()), LlmProvider)`; оба метода порта
      переопределены с теми же сигнатурами; конструктор не читает env. Ожидаемый провал
- [x] **Code**: дополнить скелет `prettyplay/llm/openai_provider.py` из Задачи 13 полной
      реализацией по каркасу выше (+ общий хелпер полей при выбранной декомпозиции); ветка
      `"openai"` в `create_provider` уже подключена скелетами Задачи 13
- [x] **Code**: `prettyplay/llm/__init__.py` — добавить `OpenAiProvider`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/test_openai_provider.py -v`
- [x] **Logic tests**:
      - `test_openai_provider_error_maps_to_llm_unavailable` — Setup: `mock.patch` клиента
        SDK: `chat.completions.create` поднимает `OpenAIError("timeout")`; env
        `OPENAI_API_KEY=test`.
        Input: `OpenAiProvider(Config(model="gpt-5")).generate_step_code(prompt="p", step_text="s",
        previous_steps=[], snapshot="- snap", screenshot=None, page_api="page.open(...)",
        existing_code=None, error=None)`.
        Assertions (verbatim):
        ```
        pytest.raises(LlmUnavailableError); "openai" in str(excinfo.value)
        isinstance(excinfo.value, PrettyplayError)
        ```
      - `test_missing_api_key_surfaces_on_first_request` — Setup:
        `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`.
        Input: `provider = OpenAiProvider(Config())` (не падает); затем вызов
        `classify_failure(...)`.
        Assertions (verbatim):
        ```
        конструкция успешна (нет исключения)
        pytest.raises(LlmUnavailableError) на первом запросе; "OPENAI_API_KEY" in str(...)
        ```
      - `test_classification_unparsable_defaults_to_incurable` — Setup: провайдер-заглушка
        SDK-ответа возвращает мусор ("sorry cannot answer" без `|`).
        Assertions (verbatim): `classification.category == "incurable"`
      - дополнительный positive: `generate_step_code` при замоканном SDK возвращает str;
        system-сообщение == prompt verbatim; модель == effective_generation_model;
        существующий base_url передан в конструктор клиента
- [x] **Debugging**: `.venv/bin/pytest tests/llm/ -x`
- [x] **Contract re-verification**: один запрос на попытку; паритет операций; ключи только из
      env; никаких секретов в логах
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`

### Task 15: `AnthropicProvider` — полный паритет (prettyplay/llm/anthropic_provider.py)

Контекст: мутация `LlmProvider::AnthropicProvider(config)`, `location: anthropic_provider.py`.
Абсолютный паритет с OpenAiProvider (те же операции, те же входы, те же выходы, та же
таксономия сбоев): ленивый клиент (`ANTHROPIC_API_KEY`); `client.messages.create(model=...,
system=prompt, max_tokens=1024, messages=[{"role":"user","content":...}])`; скриншот — блок
`{"type":"image","source":{"type":"base64","media_type":"image/png","data":...}}`; извлечение
`message.content[0].text`; `anthropic.AnthropicError` → `LlmUnavailableError("llm
unavailable: anthropic request failed") from e`. Клетка llm завершается этой задачей.

**Usages relevant to this task:**
- `anthropic`: `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`;
  `messages.create(system=..., max_tokens=1024)`; `message.content[0].text`;
  `AnthropicError` — база ошибок SDK.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 15 — AnthropicProvider
- [x] **Contract tests** (`tests/llm/test_anthropic_provider.py`): `from prettyplay.llm
      import AnthropicProvider`; наследует `LlmProvider`; сигнатуры операций идентичны
      OpenAiProvider; конструктор не читает env. Ожидаемый провал
- [x] **Code**: дополнить скелет `prettyplay/llm/anthropic_provider.py` из Задачи 13 полной
      реализацией (переиспользовать общий хелпер полей Задачи 14); ветка `"anthropic"` в
      `create_provider` уже подключена скелетами Задачи 13
- [x] **Code**: `prettyplay/llm/__init__.py` — полный фасад клетки: `LlmProvider`,
      `create_provider`, `OpenAiProvider`, `AnthropicProvider`, `FailureClassification` + `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/ -v`
- [x] **Logic tests** (зеркалируют ключевые сценарии openai — паритет):
      - `test_anthropic_provider_error_maps_to_llm_unavailable` — `mock.patch` клиента:
        `messages.create` поднимает `AnthropicError("timeout")`; env `ANTHROPIC_API_KEY=test`;
        Assertions: `pytest.raises(LlmUnavailableError)`; `"anthropic" in str(...)`;
        `isinstance(..., PrettyplayError)`
      - `test_anthropic_missing_api_key_surfaces_on_first_request` —
        `monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)`; конструкция успешна; первый
        запрос → `LlmUnavailableError` с `"ANTHROPIC_API_KEY"` в сообщении
      - edge: непарсимый вердикт классификации → `category == "incurable"`; positive:
        generate при замоканном SDK: system=prompt verbatim, max_tokens=1024, извлечение
        `content[0].text`
- [x] **Debugging**: `.venv/bin/pytest tests/llm/ -x`
- [x] **Contract re-verification**: паритет абсолютен — одинаковые входы/выходы/ошибки;
      выбор провайдера — только конфигурация
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`
- [x] Клетка llm завершена: `goga lint` — 0 ошибок; фасад-проверка:
      `.venv/bin/python -c "from prettyplay.llm import create_provider, FailureClassification"`

### Task 16: `run_step_code` + промпты — исполнение фиксированной формы (prettyplay/engine/execution.py)

Контекст: Routine клетки `prettyplay/engine`, `location: execution.py`. Исполнение кода шага
против фасада страницы: compile → изолированный namespace → `namespace["step"]` → `fn(page)`.
Исключения пробрасываются как есть; модуль не регистрируется в `sys.modules`; сетей, кроме
самой страницы, нет. Первая задача клетки engine. Промпты (inline Usages клетки engine) и
`PAGE_API_SURFACE` реализуются константами в `generator.py` — Задачей 17; verbatim-тексты
промптов приведены в шаге Code Задачи 17 (место их единственного использования).

**Usages relevant to this task:**
- `conventions`: docstrings, чистая механика.
- `facade` (from `prettyplay/driver`): источник поверхности PAGE API (для константы в Задаче 17).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
1. namespace: dict[str, object] = {}
2. exec(compile(code, "<prettyplay-step>", "exec"), namespace)
3. fn = namespace["step"]        # фиксированное имя из generation_prompt
4. fn(page)                      # исключения — наружу как есть
```

- [x] **STEP 0 (Declaration)**: объявить, что выполняется Задача 16 — run_step_code
- [x] **Contract tests** (`tests/engine/test_execution.py`): `from prettyplay.engine import
      run_step_code`; сигнатура `(code: str, page: PageFacade)`. Ожидаемый провал
- [x] **Code**: создать `prettyplay/engine/execution.py` по алгоритму выше; создать
      `prettyplay/engine/__init__.py` с реэкспортом `run_step_code`
- [x] **Interface verification**: `.venv/bin/pytest tests/engine/test_execution.py -v`
- [x] **Logic tests**:
      - `test_run_step_code_executes_fixed_form` — Setup: fake page с записью вызовов.
        Input: `run_step_code("def step(page) -> None:\n    page.open('https://example.com')\n", page)`.
        Assertions (verbatim): `page.calls == [("open", "https://example.com")]`
      - дополнительный negative: код шага, бросающий AssertionError (`def step(page):
        raise AssertionError("x")`) — исключение пробрасывается как есть (no swallow);
        edge: код без `def step(` → KeyError/исключение наружу (грубое нарушение формы —
        не штатная ситуация, защиты не требуется)
- [x] **Debugging**: `.venv/bin/pytest tests/engine/ -x`
- [x] **Contract re-verification**: изолированный namespace; без sys.modules; без LLM/сети
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/ tests/engine/`

### Task 17: `StepGenerator` — генерация с исполнением в цикле (prettyplay/engine/generator.py)

Контекст: сущность клетки engine, `location: generator.py`. Генерация работающего кода шага
с исполнением кандидатов на живой странице. Конструктор: `StepGenerator(config, provider,
cache, budgets, reporter)` — config (флаг скриншотов), provider (LLM-порт), cache (сохранение
успеха), budgets (реестр попыток), reporter (видимость). Методы `generate(identity,
step_text, previous_steps, page)` и `regenerate(identity, step_text, previous_steps, page,
existing_code, error)`. В файле определяются константы `GENERATION_PROMPT`,
`CLASSIFICATION_PROMPT` (тексты — в Задаче 16, verbatim) и `PAGE_API_SURFACE` — замороженная
строка-константа перечня вызовов PageFacade и LocatorFacade дословно из поверхности фасада
(драйвер — backward-compatibility контракт; изменения поверхности = сознательное расширение
с синхронизацией константы).

**Usages relevant to this task:**
- `generation_prompt`: system-сообщение каждого запроса генерации (verbatim).
- `facade` (from `prettyplay/driver`): единый источник поверхности PAGE API для запросов.
- `generation` (imported usage, cell .usages): цикл, бюджеты, фиксированная форма.
- `conventions`: stub-объекты вместо SDK; tmp_path для кэша.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
PAGE_API_SURFACE — замороженная строка-константа: перечень вызовов PageFacade и LocatorFacade
дословно из поверхности фасада (драйвер — backward-compatibility контракт, константа стабильна;
изменения поверхности = сознательное расширение с синхронизацией константы).

generate(identity, step_text, previous_steps, page):
  attempt = 0; existing_code = None; last_error = None
  LOOP:
    IF not budgets.try_generation(identity):
      raise IncurableStepError(step_text, "generation attempt budget exhausted",
                               "reword the step or raise generation_attempts")
    attempt += 1
    reporter.emit("on_generation_started", {"step_text": step_text, "attempt": attempt})
    snapshot = page.aria_snapshot()
    screenshot = page.screenshot() if config.send_screenshots else None
    code = provider.generate_step_code(prompt=GENERATION_PROMPT, step_text=step_text,
             previous_steps=previous_steps, snapshot=snapshot, screenshot=screenshot,
             page_api=PAGE_API_SURFACE, existing_code=existing_code, error=last_error)
    try: run_step_code(code, page); BREAK
    except Exception as e: existing_code = code; last_error = short(e)
  step = CachedStep(identity=identity, code=code, created_at=date.today().isoformat())
  cache.save(step); RETURN step

regenerate(identity, step_text, previous_steps, page, existing_code, error):
  тот же цикл; отличия: budgets.try_healing; стартовые existing_code/error из аргументов
```

Trace-чекпойнты: трактовка повторов согласована с контрактом провайдера («non-empty only on
regeneration requests») — повтор попытки с упавшим кандидатом и есть regeneration-request;
`LlmUnavailableError` из провайдера → немедленный проброс, без повтора (вне try-цикла
кандидата); исчерпание = IncurableStepError, не бесконечный цикл; максимум
`generation_attempts` (регенерация — `healing_attempts`) запросов на шаг на прогон.

- [ ] **STEP 0 (Declaration)**: объявить, что выполняется Задача 17 — StepGenerator
- [ ] **Contract tests** (`tests/engine/test_generator.py`): `from prettyplay.engine import
      StepGenerator`; сигнатура конструктора (config, provider, cache, budgets, reporter);
      методы `generate`/`regenerate` с точными сигнатурами. Ожидаемый провал
- [ ] **Code**: создать `prettyplay/engine/generator.py`: константы `GENERATION_PROMPT`,
      `CLASSIFICATION_PROMPT` (тексты ниже, verbatim), `PAGE_API_SURFACE` (поверхность
      PageFacade: open/find_by_role/find_by_label/find_by_text/aria_snapshot/screenshot/url;
      LocatorFacade: click/fill/select_option/expect_visible/expect_text/expect_enabled —
      13 вызовов дословно по таблице Surface из `prettyplay/driver/.usages/facade.md`,
      единственного источника поверхности по контракту engine; `close()` фасада в перечень
      не входит — он остаётся методом рантайма для PrettyTest.close, а не сгенерированного
      кода),
      класс `StepGenerator` по алгоритму выше (классификационный промпт используется
      StepHealer — Задача 18 импортирует его из generator либо симметрично определяет
      ссылку; канонично: обе константы в generator.py, healer импортирует CLASSIFICATION_PROMPT)

Тексты промптов (verbatim из CODEMANIFEST клетки engine; копируются в константы):

```python
GENERATION_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- PAGE API: the exact surface listing of the page facade — call nothing outside it
- CODE: the existing step code that failed (regeneration requests only)
- ERROR: the failure description of the existing code (regeneration requests only)

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page facade. Never import anything, never use other libraries
- Work only through the page API: the request carries the exact surface listing of the page facade — call nothing outside it
- For an assertion sentence end with an expectation call; for an action sentence perform the actions
- Locating by role and accessible name is preferred; by visible text next; by label for form fields
- No fixed delays, no sleeps, no explicit waits — the facade waits itself
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

CLASSIFICATION_PROMPT = """You classify a failure of a cached web UI test step.

Input you receive:
- STEP: the step sentence
- CODE: the step code that failed
- ERROR: the failure description
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached

Answer with exactly one line of the form:
category | explanation | recommendation

where category is one of:
- rot — the UI changed (selectors, texts, structure) and the step can be regenerated for the same intent
- product_defect — the step works as written but the expected behavior of the application is genuinely broken
- incurable — the step sentence no longer matches reality, the intent is ambiguous, or regeneration cannot help

explanation: one short sentence why. recommendation: one short sentence what the engineer should do.
Output only that single line — no code, no extra text."""
```
- [ ] **Code**: `prettyplay/engine/__init__.py` — добавить `StepGenerator`
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/test_generator.py -v`
- [ ] **Logic tests** (stub-провайдер с сигнатурами LlmProvider; fake page с методами фасада;
      кэш на tmp_path; рекордер событий):
      - `test_generate_success_stores_and_reports_attempt` — Setup: stub-провайдер:
        `generate_step_code` возвращает рабочий код для fake page; `budgets = RunBudgets(3, 2)`.
        Input: `generator.generate(identity, "открыть страницу", [], page)`.
        Assertions (verbatim):
        ```
        step.code == код заглушки; step.identity == identity
        provider.calls == 1; первая попытка без existing_code/error
        recorded on_generation_started: attempt == 1 (int)
        recorded on_cache_saved с filename == identity.filename
        ```
      - `test_generate_retries_with_existing_code_then_succeeds` — Setup: stub-провайдер:
        первый ответ — код, падающий на fake page (`page.find_by_role(...)` бросает
        AssertionError), второй — рабочий; рекордер.
        Input: `generator.generate(identity, "нажать Войти", [], page)`.
        Assertions (verbatim):
        ```
        provider.calls == 2
        второй вызов: existing_code == A и error содержит текст сбоя
        recorded on_generation_started ×2 (attempt 1, attempt 2)
        ```
      - `test_generate_budget_exhaustion_raises_incurable` — Setup: провайдер всегда
        возвращает код, падающий на fake page; `RunBudgets(3, 2)`; кэш tmp.
        Input: `generator.generate(identity, "невозможный шаг", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(IncurableStepError)
        excinfo.value.reason упоминает бюджет; excinfo.value.recommendation непусто
        provider.calls == 3
        cache.save не вызван (неудачи не кэшируются)
        ```
      - `test_generate_provider_unavailable_propagates_immediately` — Setup: провайдер-заглушка
        поднимает `LlmUnavailableError` в каждом вызове; счётчик вызовов.
        Input: `generator.generate(identity, "шаг", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(LlmUnavailableError)
        provider.calls == 1        # никаких повторов на инфраструктурный сбой
        budgets: израсходована 1 попытка генерации
        ```
      - дополнительный edge: `regenerate` стартует с переданных existing_code/error и
        расходует healing-бюджет (`try_healing`), не generation
- [ ] **Debugging**: `.venv/bin/pytest tests/engine/ -x`
- [ ] **Contract re-verification**: каждый запрос несёт точную PAGE_API_SURFACE; prompt
      verbatim; кэшируются только успехи
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/ tests/engine/`

### Task 18: `StepHealer` — классификация и лечение (prettyplay/engine/healer.py)

Контекст: сущность клетки engine, `location: healer.py`. Конструктор: `StepHealer(config,
provider, generator, cache, budgets, reporter)`. Метод `heal(step: CachedStep, error: str,
previous_steps: list[str], page: PageFacade) -> CachedStep` (сигнатура после D1 — с
`previous_steps`). Классификация через `provider.classify_failure` с `CLASSIFICATION_PROMPT`
(из generator.py Задачи 17); ветвление: product_defect → ProductDefectError (кэш нетронут);
incurable → IncurableStepError с полями вердикта; rot → `generator.regenerate(...)` →
`on_healed` → return healed. Клетка engine завершается этой задачей.

**Usages relevant to this task:**
- `classification_prompt`: system-сообщение запроса классификации (verbatim).
- `classification` (from `prettyplay/llm`): категории решения лечения.
- `healing` (imported usage, cell .usages): heal принимает previous_steps; раздельные лимиты.
- `taxonomy`: виды сбоев и их поля.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
heal(step, error, previous_steps, page):
  step_text = step.identity.normalized_text
  snapshot = page.aria_snapshot()
  screenshot = page.screenshot() if config.send_screenshots else None
  verdict = provider.classify_failure(prompt=CLASSIFICATION_PROMPT, step_text=step_text,
              code=step.code, error=error, snapshot=snapshot, screenshot=screenshot)
  reporter.emit("on_healing_started", {"step_text": step_text, "category": verdict.category})
  IF verdict.category == "product_defect":
    raise ProductDefectError(step_text, verdict.explanation)      # кэш не тронут
  IF verdict.category == "incurable":
    raise IncurableStepError(step_text, verdict.explanation, verdict.recommendation)
  # rot:
  healed = generator.regenerate(identity=step.identity, step_text=step_text,
             previous_steps=previous_steps, page=page,
             existing_code=step.code, error=error)
  reporter.emit("on_healed", {"step_text": step_text, "explanation": verdict.explanation})
  RETURN healed
```

- [ ] **STEP 0 (Declaration)**: объявить, что выполняется Задача 18 — StepHealer
- [ ] **Contract tests** (`tests/engine/test_healer.py`): `from prettyplay.engine import
      StepHealer`; сигнатура конструктора; метод `heal(step, error, previous_steps, page)`.
      Ожидаемый провал
- [ ] **Code**: создать `prettyplay/engine/healer.py` по алгоритму выше
- [ ] **Code**: `prettyplay/engine/__init__.py` — полный фасад клетки: `run_step_code`,
      `StepGenerator`, `StepHealer` + `__all__`
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/test_healer.py -v`
- [ ] **Logic tests**:
      - `test_heal_rot_regenerates_and_reports_healed` — Setup: провайдер-classification →
        `FailureClassification("rot", "кнопка переименована", "проверить шаг")`; регенерация
        через stub generator-объект (рекордер: regenerate(...) → возвращает вылеченный
        CachedStep); healer = StepHealer(config, provider, generator, cache, budgets, reporter).
        Input: `healer.heal(step=failed_step, error="element not found",
        previous_steps=["открыть"], page=page)`.
        Assertions (verbatim):
        ```
        возвращён вылеченный шаг
        regenerate вызван ровно 1 раз с existing_code=failed_step.code и previous_steps=["открыть"]
        recorded: on_healing_started(category="rot"), on_healed(explanation="кнопка переименована")
        cache.save не вызван напрямую healer'ом (пишет generator после успешного исполнения)
        ```
      - `test_heal_provider_unavailable_propagates` — Setup: stub-провайдер,
        `classify_failure` поднимает `LlmUnavailableError`; generator-шпион (рекордер
        вызовов); кэш-шпион (save не должен вызываться).
        Input: `healer.heal(failed_step, "err", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(LlmUnavailableError)
        generator.regenerate не вызван; cache.save не вызван
        ```
      - `test_heal_product_defect_raises_and_keeps_cache` — Setup: провайдер-classification →
        `("product_defect", "ожидание не оправдалось", "чинить продукт")`; кэш-шпион (save
        не должен вызываться); generator-шпион.
        Input: `healer.heal(failed_step, "text mismatch", ["шаг"], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(ProductDefectError); issubclass(ProductDefectError, PrettyplayError)
        generator.regenerate не вызван; cache.save не вызван
        ```
      - `test_heal_incurable_carries_verdict_fields` — Setup: провайдер-classification →
        `("incurable", "текст шага не соответствует реальности", "переформулируйте шаг")`.
        Input: `healer.heal(failed_step, "err", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(IncurableStepError)
        excinfo.value.reason == "текст шага не соответствует реальности"
        excinfo.value.recommendation == "переформулируйте шаг"
        str(excinfo.value) содержит все три поля
        ```
- [ ] **Debugging**: `.venv/bin/pytest tests/engine/ -x`
- [ ] **Contract re-verification**: анти-маскировка (product_defect всегда падает громко);
      вылеченный код заменяет кэш только после успешного исполнения
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/ tests/engine/`
- [ ] Клетка engine завершена: `goga lint` — 0 ошибок; фасад-проверка:
      `.venv/bin/python -c "from prettyplay.engine import StepGenerator, StepHealer, run_step_code"`

### Task 19: `PrettyplayRuntime` + `get_runtime` — composition root (prettyplay/runtime.py)

Контекст: две сущности одного `location: runtime.py` корневой клетки. Run-scoped composition
root: всё общее для тестов, ничего пер-тестового. `get_runtime()` — процессный синглтон
(модульная глобаль `_runtime`). Свойства: `config` (eager), `budgets = RunBudgets(
config.generation_attempts, config.healing_attempts)` (eager), `driver = DriverSession(config)`
(лениво), `provider = create_provider(config)` (лениво — construction провайдера не требует
ключей, клиент создаётся при первом запросе). `open_page() → driver.open_context()`;
`close() → driver.close()` (безопасен при незапуске). Корневой `prettyplay/__init__.py`
(сейчас пуст) начинает накапливать фасад: `PrettyplayRuntime`, `get_runtime`.

**Usages relevant to this task:**
- `conventions`: изоляция глобали в тестах (сброс до/после), `mock.patch` load_config.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
_runtime: PrettyplayRuntime | None = None (модульная глобаль)

get_runtime():
  global _runtime
  IF _runtime is None: _runtime = PrettyplayRuntime(load_config(None))
  RETURN _runtime

PrettyplayRuntime.__init__(config):
  self._config = config
  self._budgets = RunBudgets(config.generation_attempts, config.healing_attempts)
  self._driver = None; self._provider = None
config (property) → self._config
budgets (property) → self._budgets
driver (property): лениво self._driver = DriverSession(self._config)
provider (property): лениво self._provider = create_provider(self._config)
open_page() → self.driver.open_context()
close() → IF self._driver: self._driver.close()
```

- [ ] **STEP 0 (Declaration)**: объявить, что выполняется Задача 19 — PrettyplayRuntime + get_runtime
- [ ] **Contract tests** (`tests/test_runtime.py`): `from prettyplay import
      PrettyplayRuntime, get_runtime`; свойства `config`/`budgets`/`driver`/`provider`;
      методы `open_page`/`close`; `get_runtime()` вызываем без аргументов. Ожидаемый провал
- [ ] **Code**: создать `prettyplay/runtime.py` по алгоритму выше; заполнить
      `prettyplay/__init__.py`: `from .runtime import PrettyplayRuntime, get_runtime` +
      начало `__all__`
- [ ] **Interface verification**: `.venv/bin/pytest tests/test_runtime.py -v`; фасад:
      `.venv/bin/python -c "from prettyplay import PrettyplayRuntime, get_runtime"`
- [ ] **Logic tests**:
      - `test_get_runtime_is_process_singleton` — Setup: изоляция глобали (сброс приватной
        глобали до/после); `mock.patch` load_config → фиксированный Config.
        Input: `get_runtime()` ×2.
        Assertions (verbatim):
        ```
        runtime1 is runtime2
        load_config вызван ровно 1 раз
        ```
      - `test_runtime_constructs_without_llm_credentials` — Setup: `monkeypatch.delenv`
        обоих ключей; runtime-глобаль изолирована.
        Input: `runtime = PrettyplayRuntime(Config(model="gpt-5"))`; чтение `runtime.config`,
        `runtime.budgets`.
        Assertions (verbatim):
        ```
        конструкция без исключений
        runtime.provider ещё не создавался (лениво) — обращение к нему вне теста не требуется
        ```
      - дополнительный edge: `close()` до любого `open_page()` — no-op; `budgets` — RunBudgets
        с лимитами из config
- [ ] **Debugging**: `.venv/bin/pytest tests/test_runtime.py -x`
- [ ] **Contract re-verification**: конструкция рантайма без кредов; один рантайм на процесс;
      повторные вызовы дёшевы
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/runtime.py prettyplay/__init__.py tests/test_runtime.py`

### Task 20: `StepExecutor` — цикл шага (prettyplay/executor.py)

Контекст: сущность корня, `location: executor.py`. Конструктор: `StepExecutor(cache_key,
cache, generator, healer, budgets, reporter)` + per-test состояние `self._scenario:
list[str]` (сценарный контекст теста). `execute(step_text, step_type, page)`: полный цикл —
hit → исполнить; miss → сгенерировать; сбой кэша → лечить. Внутренний хелпер `short(exc)` —
первая строка `str(exc)`, обрезанная до 200 символов.

**Usages relevant to this task:**
- `generation`, `healing` (from `prettyplay/engine`): циклы, которым executor делегирует.
- `taxonomy` (from `prettyplay/failures`): виды сбоев, пробрасываемые с on_step_failed.
- `conventions`: stub-объекты провайдера/страницы.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
__init__(cache_key, cache, generator, healer, budgets, reporter):
  состояния + self._scenario: list[str] = []   # сценарный контекст теста
execute(step_text, step_type, page):
  reporter.emit("on_step_started", {"step_text": step_text, "step_type": step_type})
  identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
                          normalized_text=normalize_step_text(step_text))
  cached = cache.load(identity)
  IF cached is not None:
    try:
      run_step_code(cached.code, page)
    except Exception as e:
      self._healer.heal(cached, short(e), self._scenario, page)   # вылечен = переисполнен
  ELSE:
    self._generator.generate(identity, step_text, self._scenario, page)
  self._scenario.append(step_text)
  reporter.emit("on_step_passed", {"step_text": step_text, "step_type": step_type})
  # ANY raise из веток выше:
  except-обёртка всего тела: reporter.emit("on_step_failed", {"step_text": step_text,
    "step_type": step_type, "error": short(exc)}); raise
short(exc) → первая строка str(exc), обрезанная до 200 символов
```

Документированная интерпретация (verbatim из дизайна, обязана соблюдаться реализацией):
шаг подпадает под классификацию (и значит под ProductDefectError) только после первой
успешной генерации и сохранения в кэш; шаг, который ни разу не сгенерировался, даёт
`IncurableStepError` и никогда `ProductDefectError`.

- [ ] **STEP 0 (Declaration)**: объявить, что выполняется Задача 20 — StepExecutor
- [ ] **Contract tests** (`tests/test_executor.py`): `from prettyplay import StepExecutor`;
      сигнатура конструктора; метод `execute(step_text, step_type, page)`. Ожидаемый провал
- [ ] **Code**: создать `prettyplay/executor.py` по алгоритму выше (делегирование движку,
      on_step_failed + проброс в except-обёртке всего тела)
- [ ] **Code**: `prettyplay/__init__.py` — добавить `from .executor import StepExecutor` в
      реэкспорты и `__all__`
- [ ] **Interface verification**: `.venv/bin/pytest tests/test_executor.py -v`
- [ ] **Logic tests** (fake page; кэш на tmp_path; stub generator/healer-рекордеры):
      - hit-путь: предзаписанный в кэш шаг → `run_step_code` исполняется, generator/healer
        не вызваны, `on_step_started`/`on_step_passed` записаны (step_type передан верно)
      - miss-путь: пустой кэш → `generator.generate` вызван с identity и `previous_steps`;
        после успеха — `on_step_passed`; сценарный контекст растёт (`_scenario` пополняется
        оригинальными предложениями — через поведение второго шага)
      - сбой ветки: generator поднимает IncurableStepError → `on_step_failed` записан с
        короткой ошибкой; исключение проброшено тем же видом
      - edge: `short()` — многострочная ошибка → первая строка до 200 символов в
        `on_step_failed`
- [ ] **Debugging**: `.venv/bin/pytest tests/test_executor.py -x`
- [ ] **Contract re-verification**: кэш-путь без LLM; сценарный контекст пер-тестовый;
      проброс по виду с on_step_failed
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/executor.py tests/test_executor.py`

### Task 21: `PrettyTest` — главный объект интегратора (prettyplay/scenario.py)

Контекст: сущность корня, `location: scenario.py`. Один инстанс на тест; владеет адресацией
кэша и изолированным контекстом браузера теста; цикл шагов делегирован executor'у. Конструктор
`PrettyTest(cache_key, cache_path=None)`: `runtime = get_runtime()`; `reporter =
StepReporter(hooks=[])`; `cache = StepCache(runtime.config, cache_path, reporter)`;
`generator = StepGenerator(runtime.config, runtime.provider, cache, runtime.budgets,
reporter)`; `healer = StepHealer(runtime.config, runtime.provider, generator, cache,
runtime.budgets, reporter)`; `executor = StepExecutor(cache_key, cache, generator, healer,
runtime.budgets, reporter)`; страница лениво. Контекст-менеджер: `__enter__` → self,
`__exit__` → close() (не гасит исключения). Корневой фасад завершается этой задачей.

**Usages relevant to this task:**
- `hooks` (from `prettyplay/reporting`): add_hooks регистрирует StepHooks до первого шага.
- `taxonomy`: сбои шагов пробрасываются по виду.
- `steps`, `lifecycle` (cell .usages — API главного объекта): action/assertion/close.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim из дизайна):
```
__init__(cache_key, cache_path=None):
  self._runtime = get_runtime()
  self._reporter = StepReporter(hooks=[])
  self._cache = StepCache(self._runtime.config, cache_path, self._reporter)
  self._generator = StepGenerator(self._runtime.config, self._runtime.provider,
                                  self._cache, self._runtime.budgets, self._reporter)
  self._healer = StepHealer(self._runtime.config, self._runtime.provider, self._generator,
                            self._cache, self._runtime.budgets, self._reporter)
  self._executor = StepExecutor(cache_key, self._cache, self._generator, self._healer,
                                self._runtime.budgets, self._reporter)
  self._page = None
cache_key (property) → self._executor-ключ (для диагностики)
_page(): IF self._page is None: self._page = self._runtime.open_page(); RETURN self._page
action(text)    → self._executor.execute(text, "action",    self._page())
assertion(text) → self._executor.execute(text, "assertion", self._page())
add_hooks(hooks)→ self._reporter.hooks.append(hooks)
close()         → IF self._page: self._page.close(); self._page = None
__enter__ → self;  __exit__ → close(); return None (не гасит исключения)
```

Чекпойнт: обращение к `runtime.provider` в конструкторе безопасно — клиент ленивый
(конструкция без кредов).

- [ ] **STEP 0 (Declaration)**: объявить, что выполняется Задача 21 — PrettyTest
- [ ] **Contract tests** (`tests/test_scenario.py`): `from prettyplay import PrettyTest`;
      свойство `cache_key`; методы `action(text)`/`assertion(text)`/`add_hooks(hooks)`/
      `close()`; контекст-менеджер. Ожидаемый провал
- [ ] **Code**: создать `prettyplay/scenario.py` по алгоритму выше
- [ ] **Code**: `prettyplay/__init__.py` — полный фасад корня:
      `from .scenario import PrettyTest`, `from .executor import StepExecutor`,
      `from .runtime import PrettyplayRuntime, get_runtime`; `__all__ = ["PrettyTest",
      "StepExecutor", "PrettyplayRuntime", "get_runtime"]`
- [ ] **Interface verification**: `.venv/bin/pytest tests/test_scenario.py -v`; фасад:
      `.venv/bin/python -c "from prettyplay import PrettyTest"`
- [ ] **Logic tests** (runtime-глобаль изолирована; mock `runtime.open_page` → fake page):
      - `test_prettytest_context_manager_closes_page` — Setup: runtime-глобаль изолирована;
        `mock` runtime.open_page → fake page с рекордом close().
        Input:
        ```python
        with PrettyTest("k") as t:
            t.action("шаг")
        ```
        Assertions (verbatim):
        ```
        page.closed is True; runtime.close не вызван (рантайм жив)
        второй with: новая страница, тот же runtime
        ```
      - дополнительный positive: `add_hooks(hooks)` аппендит в reporter.hooks (виден в
        fan-out следующего шага); `cache_key` property возвращает переданный ключ;
        конструкция не открывает браузер (open_page не вызван до первого шага); edge:
        `close()` дважды — no-op; `__exit__` не гасит исключение (пробрасывается)
- [ ] **Debugging**: `.venv/bin/pytest tests/test_scenario.py -x`
- [ ] **Contract re-verification**: конструкция дешёвая (браузер и страница ленивы);
      кросс-тестового состояния нет
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/ tests/`
- [ ] Корневая клетка завершена: `goga lint` — 0 ошибок; фасад-проверка полного корня

### Task 22: Интеграционные тесты полного цикла шага (tests/test_integration.py)

Контекст: кросс-сущностные сценарии через публичный фасад `PrettyTest` — центральные обещания
продукта: кэшированный прогон вообще не требует LLM (Поток B), сценарный контекст питает
следующую генерацию (Поток A), кэшированный шаг сломан → самолечение (Поток C). Провайдер —
заглушка с сигнатурами `LlmProvider`, бросающая AssertionError при нарушении «кэш-путь без
LLM» (детект нарушения); страница — fake-объект с методами фасада; runtime-глобаль изолирована
и сбрасывается; env без ключей; файловый кэш — только `tmp_path`. По conventions
интеграционные тесты лежат прямо в `tests/`.

**Usages relevant to this task:**
- `hooks`: рекордер событий для проверки on_step_started/on_step_passed.
- `taxonomy`: виды сбоев на границе.
- `conventions`: интеграционные тесты мультипакетных сценариев — в `tests/` напрямую.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Create test file `tests/test_integration.py` (общие фикстуры: изолированный runtime с
      tmp-кэшем, провайдер-заглушка, fake page, рекордер хуков)
- [ ] `test_action_cached_step_runs_without_llm` — Setup: `tmp_path`-кэш с предзаписанным
      файлом шага (валидный модуль для «открыть страницу логина»); runtime-глобаль сброшена;
      env без ключей; провайдер-заглушка, бросающий `AssertionError("provider must not be
      called")` при любом вызове (детект нарушения); page подменена на fake (mock
      runtime.open_page).
      Input: `t = PrettyTest("login-flow"); t.action("открыть страницу логина"); t.close()`.
      Assertions (verbatim):
      ```
      шаг завершился без исключений
      recorded: on_step_started, on_step_passed (step_type="action")
      провайдер-заглушка не вызвана (кэш-путь без LLM)
      ```
- [ ] `test_scenario_context_feeds_next_generation` — Setup: кэш пуст; провайдер-заглушка
      возвращает рабочий код; рекордер предыдущих шагов в запросах; fake page.
      Input: `t = PrettyTest("k"); t.action("шаг один"); t.action("шаг два"); t.close()`.
      Assertions (verbatim):
      ```
      второй запрос провайдера получил previous_steps == ["шаг один"]
      первый — []
      ```
- [ ] Дополнительный интеграционный сценарий (Поток C из дизайна): кэшированный шаг,
      падающий на fake page; провайдер-classification → rot; регенерация возвращает рабочий
      код → шаг проходит, файл кэша перезаписан, записаны on_healing_started(category="rot")
      и on_healed, затем on_step_passed
- [ ] Test edge case: `PrettyTest` с `cache_path` — шаги разных подкаталогов не collide
      (адрес включает подкаталог)
- [ ] Run validation: `.venv/bin/pytest tests/ -x` — весь набор зелёный;
      `.venv/bin/ruff check prettyplay/ tests/` — 0 ошибок;
      `.venv/bin/python -c "from prettyplay import PrettyTest"` — фасад корня

---

## Validation Commands

- `.venv/bin/pytest tests/ -x`: Run all tests (полный набор; финальная проверка плана)
- `.venv/bin/pytest tests/<клетка>/test_<module>.py -v`: Run a specific test (в каждой задаче)
- `.venv/bin/ruff check prettyplay/ tests/`: Lint check (line-length 120, complexity 10)
- `.venv/bin/python -c "from prettyplay import PrettyTest"`: Verify root facade importable
- `.venv/bin/python -c "from prettyplay.config import Config, load_config"`: config facade
- `.venv/bin/python -c "from prettyplay.reporting import StepHooks, StepReporter"`: reporting facade
- `.venv/bin/python -c "from prettyplay.failures import PrettyplayError, ProductDefectError, IncurableStepError, LlmUnavailableError"`: failures facade
- `.venv/bin/python -c "from prettyplay.driver import DriverSession, PageFacade, LocatorFacade"`: driver facade
- `.venv/bin/python -c "from prettyplay.cache import StepCache"`: cache facade (дословно из storage.md)
- `.venv/bin/python -c "from prettyplay.llm import create_provider, FailureClassification"`: llm facade
- `.venv/bin/python -c "from prettyplay.engine import StepGenerator, StepHealer, run_step_code"`: engine facade
- `goga lint`: Verify cells (8 клеток, 0 ошибок; после каждой завершённой клетки)

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
- [ ] Every contract entity is accessible from the facade (8 `__init__.py` + `__all__`)
- [ ] Properties and methods match the declared API (сигнатуры дословно из CODEMANIFEST)
- [ ] Descriptions are reflected in behavior (алгоритмы дизайна реализованы как указано)
- [ ] Contract dependencies are met (Imports разрешены относительными импортами клеток)
- [ ] Re-exports are accessible from the facade
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification →
      logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist where cross-entity scenarios require them (Task 22)
- [ ] No package boundary was expanded (новых клеток нет; импорты внутри пакета относительные)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass
- [ ] Every Usages entry is mentioned in at least one task (Phase 2 calibration):
      `conventions` — все задачи; `pydantic` — 2/3/9/12; `playwright` — 6/7; `openai` — 14;
      `anthropic` — 15; `generation_prompt` — 17; `classification_prompt` — 17/18;
      imported `hooks` — 4/10/21; `taxonomy` — 5/13/18/20; `generation`/`healing` — 17/18/20;
      `facade` — 7/16/17; `classification` — 12/18
