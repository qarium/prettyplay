# Design Document: `the-first-version`

Полная архитектурная спецификация реализации Prettyplay — UI-тесты на человеческом языке с
репозиторным кэшем шагов, генерацией кода через LLM и самолечением. Документ выведен из
контрактов CODEMANIFEST восьми клеток, материализованных стадией apply-architecture, и прошёл
фазы валидации контрактов, трассировки и алгоритмизации скилла goga-design-by-changes.
Реализационный код на этой стадии не пишется — фиксируется «что» и «как» реализовать.

---

## Contract Changes

### Changed CODEMANIFEST Files

Greenfield-проект: до стадии кода не существовало ни одной клетки (только пустой
`prettyplay/__init__.py`). Все 8 манифестов — новые; git-статус `??` (untracked), дифф против
`master` пуст, поэтому change list собран по факту создания:

- `prettyplay/CODEMANIFEST` — фасад библиотеки: `PrettyTest`, `StepExecutor`, `PrettyplayRuntime`, `get_runtime` (NEW)
- `prettyplay/config/CODEMANIFEST` — настройки: `Config`, `load_config` (NEW)
- `prettyplay/reporting/CODEMANIFEST` — видимость: `StepHooks`, `StepReporter` (NEW)
- `prettyplay/failures/CODEMANIFEST` — таксономия сбоев: `PrettyplayError` + 3 мутации (NEW)
- `prettyplay/driver/CODEMANIFEST` — Playwright-драйвер: `DriverSession`, `PageFacade`, `LocatorFacade` (NEW)
- `prettyplay/cache/CODEMANIFEST` — кэш шагов: `normalize_step_text`, `StepIdentity`, `CachedStep`, `StepCache`, `RunBudgets` (NEW)
- `prettyplay/llm/CODEMANIFEST` — LLM-порт: `LlmProvider` + 2 мутации, `create_provider`, `FailureClassification` (NEW)
- `prettyplay/engine/CODEMANIFEST` — движок: `run_step_code`, `StepGenerator`, `StepHealer` (NEW)

### New Entities

| Сущность | Клетка | location | Вид |
|---|---|---|---|
| `Config` | config | models.py | Entity (12 properties: 10 полей + 2 вычисляемых) |
| `load_config` | config | loader.py | Routine |
| `StepHooks` | reporting | hooks.py | Entity (8 no-op методов) |
| `StepReporter` | reporting | reporter.py | Entity (emit) |
| `PrettyplayError` | failures | errors.py | Entity (база) |
| `ProductDefectError` / `IncurableStepError` / `LlmUnavailableError` | failures | errors.py | Мутации `PrettyplayError::` |
| `DriverSession` | driver | session.py | Entity (open_context, close) |
| `PageFacade` | driver | page.py | Entity (7 методов + url) |
| `LocatorFacade` | driver | page.py | Entity (6 методов) |
| `normalize_step_text` | cache | text.py | Routine (чистая функция) |
| `StepIdentity` | cache | models.py | Entity (4 properties, вкл. filename) |
| `CachedStep` | cache | models.py | Entity (3 properties) |
| `StepCache` | cache | store.py | Entity (load, save + root, writable) |
| `RunBudgets` | cache | budgets.py | Entity (try_generation, try_healing) |
| `LlmProvider` | llm | provider.py | Entity (generate_step_code, classify_failure) |
| `OpenAiProvider` / `AnthropicProvider` | llm | *_provider.py | Мутации `LlmProvider::` |
| `create_provider` | llm | provider.py | Routine |
| `FailureClassification` | llm | models.py | Entity (3 properties) |
| `run_step_code` | engine | execution.py | Routine |
| `StepGenerator` | engine | generator.py | Entity (generate, regenerate) |
| `StepHealer` | engine | healer.py | Entity (heal) |
| `PrettyTest` | root | scenario.py | Entity (action, assertion, add_hooks, close + cache_key) |
| `StepExecutor` | root | executor.py | Entity (execute) |
| `PrettyplayRuntime` | root | runtime.py | Entity (open_page, close + 4 properties) |
| `get_runtime` | root | runtime.py | Routine (процессный синглтон) |

### Changed Entities

Нет — все сущности новые.

### Deleted Entities

Нет.

### Usages and Annotations Changes

- Одобрены и применены 3 исправления контрактов (см. Applied Fixes): сигнатура `heal`, тип
  payload `emit`, properties ошибок таксономии.
- Обновлены 2 клеточных usage-файла (см. раздел `.usages/` Update): `healing.md`, `hooks.md`.

---

## Applied Fixes

### Fixed CODEMANIFEST Defects

Все три дефекта найдены аудитом согласованности (Phase 3), одобрены пользователем (вариант A)
и применены; повторный `goga lint` — 8 клеток, 0 ошибок.

1. **`prettyplay/engine/CODEMANIFEST` → `StepHealer.heal`**:
   `heal(step: CachedStep, error: str, page: PageFacade)` →
   `heal(step: CachedStep, error: str, previous_steps: list[str], page: PageFacade)`
   (reason: Interface↔Interface — контракту неоткуда было взять `previous_steps`, обязательный
   для `StepGenerator.regenerate`; сценарным контекстом владеет `StepExecutor`).
   Сопутствующая правка в `prettyplay/CODEMANIFEST` → `StepExecutor.execute`, шаг 4 алгоритма:
   «delegate to the healer heal with the failure description **and the scenario context**».
2. **`prettyplay/reporting/CODEMANIFEST` → `StepReporter.emit`**:
   `payload: dict[str, str]` → `payload: dict[str, str | int]`
   (reason: Interface↔Type — `on_generation_started(step_text: str, attempt: int)` требует
   int-значение; строковый payload несовместим с контрактом хука).
3. **`prettyplay/failures/CODEMANIFEST` → properties ошибок**
   (reason: Annotations↔Entity — аннотации требуют «carries all three fields», практика
   taxonomy.md читает `info.value.recommendation`, но поля были только параметрами конструктора):
   - `ProductDefectError`: + `step_text -> str`, `message -> str`
   - `IncurableStepError`: + `step_text -> str`, `reason -> str`, `recommendation -> str`
   - `LlmUnavailableError`: + `message -> str`

---

## Entity Interaction and Data Flow

### Interaction Diagram

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

### Data Flows

**Поток A — шаг при промахе кэша (первый прогон).**
`PrettyTest.action(text)` → лениво `PrettyplayRuntime.open_page()` → `DriverSession.open_context()`
(ленивый запуск браузера) → `PageFacade` → `StepExecutor.execute(text, "action", page)` →
`emit("on_step_started")` → `normalize_step_text(text)` → `StepIdentity` → `StepCache.load` →
`None` → `StepGenerator.generate(identity, text, previous_steps, page)`: `RunBudgets.try_generation`
→ `emit("on_generation_started", attempt)` → `page.aria_snapshot()` (+ `screenshot()` при
`send_screenshots`) → `LlmProvider.generate_step_code(generation_prompt, …, page_api, None, None)`
→ `run_step_code(code, page)` → успех → `CachedStep(identity, code, created_at)` →
`StepCache.save` (tmp + `os.replace`, `emit("on_cache_saved")`) → executor дополняет сценарный
контекст → `emit("on_step_passed")`.

**Поток B — шаг при попадании (кэшированный прогон, без LLM).**
`execute` → `load` → `CachedStep` → `run_step_code(cached.code, page)` → успех → контекст →
`on_step_passed`. Провайдер не создаётся, сеть не трогается (кроме страницы), ключи не нужны.

**Поток C — кэшированный шаг сломан (гниение) → самолечение.**
`run_step_code` выбросил исключение → короткое описание ошибки → `StepHealer.heal(step, error,
previous_steps, page)` → сбор входов классификации → `LlmProvider.classify_failure(classification_prompt,
…)` → `FailureClassification` → `emit("on_healing_started", category)` → при `rot`:
`StepGenerator.regenerate(identity, text, previous_steps, page, existing_code, error)` — цикл с
бюджетом `try_healing`, кандидат исполняется, успех → `cache.save` (перезапись того же файла,
атомарно) → `emit("on_healed")` → executor: контекст + `on_step_passed`.

**Поток D — конфигурация.**
`get_runtime()` (первый вызов) → `load_config(None)`: поиск pyproject.toml вверх от cwd →
tomllib/tomli → секция `[tool.prettyplay]` → env-оверрайды `PRETTYPLAY_*` → валидация `Config`
→ `PrettyplayRuntime(config)`.

### Entity Dependencies

Порядок инициализации (снизу вверх, DAG без циклов; подтверждено `goga schema`):

```
config, reporting, failures          — листья
driver        ← config
cache         ← config, reporting
llm           ← config, failures
engine        ← config, reporting, failures, driver, cache, llm
prettyplay    ← все семь
```

Порядок создания объектов в рантайме: `load_config` → `PrettyplayRuntime` (config eagerly;
`RunBudgets` eagerly; `DriverSession` и `LlmProvider` — лениво) → на тест: `StepReporter` →
`StepCache` → `StepGenerator` → `StepHealer` → `StepExecutor` → лениво `PageFacade` (первый шаг).

---

## Code Stack Trace

Трассировка выполнена по всем точкам входа контракта с контрольными точками типов и логики
после каждого шага. Сводно по клеткам; все чекпойнты пройдены (дефектов после фиксов D1–D3 нет).

### Trace: `load_config`

#### Chain
1. **Input**: `pyproject_path: str | None` (None — авто-поиск) → checkpoint: тип допускает оба режима ✓
2. Разрешение пути: явный аргумент, иначе подъём от cwd до первого `pyproject.toml`
   (`pathlib.Path.cwd().parents`) → checkpoint: найденный путь — `Path`, существует ✓
3. Парсинг TOML: `sys.version_info >= (3, 11)` → `tomllib`, иначе `tomli` (см. `pydantic`)
   → checkpoint: `dict` ✓
4. Извлечение `data.get("tool", {}).get("prettyplay", {})` — отсутствующая секция = пустая
   → checkpoint: отсутствие секции не ошибка ✓ (контракт: «a missing section is an empty section»)
5. Env-оверрайды: для каждого из 10 полей — `PRETTYPLAY_<UPPER>` применяется, если переменная
   задана (`os.environ.get(name) is not None`, включая пустое значение — по контракту
   «when the variable is set»)
   → checkpoint: str из env коэрсится pydantic v2 (lax) в `int`/`bool` — "3"→3, "false"→False ✓;
   пустая строка в str-поле легальна (пустое значение настройки), пустая строка в int/bool-поле —
   громкая ValidationError с именем настройки ✓
6. `Config(**merged)` → checkpoint: невалидное значение → pydantic-ошибка с именем поля, громко,
   actionable ✓
7. `cache_root == ""` → абсолютный `<pyproject_dir>/.prettyplay/cache/` → checkpoint: поле всегда
   абсолютный путь после load ✓
8. **Output**: `Config` — единственный источник неизменяемых настроек ✓

#### Checkpoint Summary
- Типы входа/выхода: passed
- Коэрсция env → int/bool: passed (pydantic lax mode)
- Разрешение cache_root: passed

### Trace: `Config`

1. **Input**: kwargs (`kw_only=True`, все поля с пустыми дефолтами: provider="openai",
   browser="chromium", model="", attempts 3/2, send_screenshots=False) ✓
2. Валидаторы: `provider ∈ {openai, anthropic}`, `browser ∈ {chromium, firefox, webkit}`,
   `generation_attempts > 0`, `healing_attempts > 0` (field_validator / Literal + GT)
   → checkpoint: невалидное — ValidationError, имя поля в сообщении ✓
3. Вычисляемые: `effective_generation_model` = `generation_model or model`; аналогично classification
   → checkpoint: пустая строка фолбэчится на `model` ✓
4. **Output**: иммутабельная модель pydantic (model_config frozen не обязателен; контракт требует
   лишь «single source of the immutable configuration part» — одну загрузку на прогон) ✓

### Trace: `StepReporter.emit`

1. **Input**: `event: str`, `payload: dict[str, str | int]` → checkpoint: имена event совпадают
   с методами `StepHooks` один-в-один ✓
2. `logger = logging.getLogger("prettyplay")`; `extra` строится санитизацией payload (см.
   Algorithm Design — коллидирующие с LogRecord ключи получают префикс `ctx_`); `logger.log(level,
   event, extra=extra)`
   → checkpoint: ключ `filename` события on_cache_saved коллидирует с зарезервированным атрибутом
   LogRecord — `Logger.makeRecord` бросает `KeyError: "Attempt to overwrite 'filename' in
   LogRecord"` (эмпирически подтверждено на Python 3.12 при включённом уровне) — коллизия устранена
   санитизацией: в лог-записи ключ `ctx_filename`, хуки получают оригинальные kwargs `**payload`
   ✓; остальные ключи payload (step_text, step_type, error, attempt, category, explanation,
   recommendation, reason) зарезервированными не являются ✓; уровни: жизненный цикл — INFO,
   пропуск записи кэша и сбой хука — WARNING ✓
3. Для каждого хука в порядке регистрации: `getattr(hook, event)(**payload)` в try/except
   → checkpoint: исключение хука → `logger.warning` + пропуск, прогон продолжается ✓
4. **Output**: side effects (log + вызовы хуков), ничего не возвращает ✓

### Trace: `StepHooks`

База с 8 no-op методами; переопределяются интегратором. Контракт синхронный, без очередей и
ретраев ✓. Payload-типы соответствуют emit: `attempt: int`, остальные — str ✓ (после D2).

### Trace: `PrettyplayError` (+ мутации)

1. **Input**: message / (step_text, message) / (step_text, reason, recommendation) ✓
2. Поля сохраняются как атрибуты (properties объявлены после D3) ✓
3. `IncurableStepError.__str__` рендерит все три поля ✓ (требование «rendered message includes
   each of them»)
4. **Output**: три различимых вида, все ловятся одним `except PrettyplayError` ✓

### Trace: `DriverSession.open_context` / `close`

1. **Input**: без аргументов (состояние — config) ✓
2. Ленивый старт: конструктор ничего не запускает; первый вызов — `sync_playwright().start()`
   (сессия живёт весь прогон, поэтому явный start, не `with`-блок), затем
   `browsers[config.browser].launch()` — словарь `{chromium, firefox, webkit}` по cook'у
   → checkpoint: браузер запускается ровно один раз на прогон ✓
3. `browser.new_context()` → `context.new_page()` → обёртка `PageFacade(page, context)`
   → checkpoint: каждая страница — свой изолированный контекст ✓
4. `close()`: если браузер запущен — `browser.close()` + `playwright.stop()`; иначе no-op
   → checkpoint: безопасен при незапуске ✓
5. **Output**: `PageFacade` ✓

### Trace: `PageFacade` / `LocatorFacade`

- `open(url)` → `page.goto(url)` (сам ждёт "load") ✓
- `find_by_role(role, name)` → `page.get_by_role(role, name=name)` → `LocatorFacade` ✓
- `find_by_label(label)` → `page.get_by_label(label)` ✓
- `find_by_text(text)` → `page.get_by_text(text)` ✓
- `aria_snapshot()` → `page.locator("body").aria_snapshot()` (по cook'у — первичный ввод LLM) ✓
- `screenshot()` → `page.screenshot(full_page=True)` → `bytes` ✓
- `url` → `page.url` ✓; `close()` → `context.close()` (браузер жив) ✓
- `LocatorFacade`: `click`→`locator.click`; `fill`→`locator.fill(value)`;
  `select_option`→`locator.select_option(value)`; `expect_visible`→`expect(loc).to_be_visible()`;
  `expect_text`→`expect(loc).to_contain_text(text)` (дизъюнкция «equals or contains» = contains,
  супер-множество equals); `expect_enabled`→`expect(loc).to_be_enabled()`
  → checkpoint: все ожидания — через `playwright.sync_api.expect`, авто-ожидания, без fixed
  delays ✓; неуспешное ожидание бросает AssertionError → «destined for failure classification» ✓
  → checkpoint: наружу не отдаётся ни один сырой объект Playwright (типы возврата — str/bytes/
  LocatorFacade) ✓

### Trace: `normalize_step_text`

1. **Input**: `text: str` ✓
2. `unicodedata.normalize("NFC", text)` → `.strip()` → `re.sub(r"\s+", " ", …)` → `.casefold()`
   → checkpoint: чистая функция, без I/O и локали ✓; «Нажать Войти» ≡ «нажать  войти » ✓
3. **Output**: `normalized: str` ✓

### Trace: `StepIdentity`

1. **Input**: тройка (cache_key, step_type, normalized_text), kw_only ✓
2. `filename`: `identity_string = "\x1f".join((cache_key, step_type, normalized_text))`
   (Unit Separator — не вводится с клавиатуры, не встречается в предложениях) →
   `hashlib.sha256(identity_string.encode("utf-8")).hexdigest()` → `f"{digest}.py"`
   → checkpoint: имя файла не обязано быть python-идентификатором (hex-дайджест может
   начинаться с цифры) — load разбирает текст файла, import по имени не выполняется ✓;
   детерминизм и различимость троек ✓ (sha256)
3. **Output**: модель с вычисляемым `filename` ✓

### Trace: `StepCache.load`

1. **Input**: `identity: StepIdentity` ✓
2. Целевой файл: `root / (path или "") / identity.filename` → отсутствует → `None`
   → checkpoint: промах — не ошибка ✓
3. Чтение текста модуля: разбор метаданных-заголовка (модульные константы `STEP_TEXT`,
   `CACHE_KEY`, `STEP_TYPE`, `CREATED_AT`), хвост от первого `def step(` — код
   → checkpoint: формат фиксированный, файл — валидный python-модуль (требование CachedStep);
   контроль соответствия `CACHE_KEY`/`STEP_TYPE`/`STEP_TEXT` запрошенной identity — при
   расхождении (ручная правка файла) → `None` (защитный промах) ✓; структурно повреждённый
   файл (невалидный заголовок/литерал, отсутствие полей или хвоста `def step(`, нечитаемый
   файл) → `None` (защитный промах, прогон не падает — контракт «The cache is always read») ✓
4. **Output**: `CachedStep | None` ✓

### Trace: `StepCache.save`

1. **Input**: `step: CachedStep` ✓
2. Каталог: `os.makedirs(target_dir, exist_ok=True)`; проверка writability (см. Algorithm Design)
   → read-only → `emit("on_cache_skipped", reason="read-only cache")` и выход
   → checkpoint: прогон не падает ✓
3. Сериализация: заголовок-константы через `repr()` значений + пустая строка + код шага
   → checkpoint: сгенерированный файл импортируем ✓
4. Временный файл в целевом каталоге (`tempfile.mkstemp(dir=target_dir, prefix=".tmp-", suffix=".py")`) →
   `os.replace(tmp, target)` → checkpoint: атомарно, частичный файл невидим ✓
5. Windows, цель занята: короткий цикл повторов replace (3 попытки, пауза 0.1 с — библиотечный
   бэкофф, не страничное ожидание) → не помогло → `on_cache_skipped` → checkpoint: прогон не
   падает, последняя победившая запись при конкурентных писателях ✓
6. Успех → `emit("on_cache_saved", {"step_text": identity.normalized_text, "filename": …})` ✓
7. **Output**: side effect — файл в репозитории ✓

### Trace: `RunBudgets.try_generation` / `try_healing`

1. **Input**: `identity: StepIdentity` ✓
2. Ключ реестра — `identity.filename: str` (детерминированный, без коллизий; pydantic-модели
   по умолчанию нехешируемы — строковый ключ проще и надёжнее)
3. `counters_gen[key] < generation_limit` → инкремент, `True`; иначе `False`. Аналогично healing
   отдельным словарём → checkpoint: раздельные лимиты, один реестр на процесс ✓
4. **Output**: `allowed: bool`; `False` → вызывающий превращает в IncurableStepError ✓

### Trace: `create_provider`

1. `config.provider == "openai"` → `OpenAiProvider(config)`; `"anthropic"` → `AnthropicProvider(config)`
2. Неизвестное значение → громкая actionable-ошибка со списком поддерживаемых
   → checkpoint: двойная защита (Config уже валидирует Literal — belt and suspenders) ✓
3. **Output**: `LlmProvider` ✓

### Trace: `OpenAiProvider` / `AnthropicProvider` (паритет)

1. **Input**: `config: Config` ✓
2. Ленивый клиент: конструктор НЕ читает env (требование рантайма: «Constructing the runtime
   never requires LLM credentials») ✓; при первом запросе — `os.environ["OPENAI_API_KEY"]` /
   `["ANTHROPIC_API_KEY"]`; отсутствие/пустота → `LlmUnavailableError` с именем провайдера и
   переменной ✓; `config.base_url` непуст → передаётся в конструктор клиента ✓
3. `generate_step_code(prompt, step_text, previous_steps, snapshot, screenshot, page_api,
   existing_code, error)`:
   - openai: `client.chat.completions.create(model=config.effective_generation_model,
     messages=[{"role":"system","content":prompt}, {"role":"user","content": user_content}])`,
     где user_content — текстовый блок с полями STEP / PREVIOUS STEPS / PAGE SNAPSHOT / PAGE API
     / CODE / ERROR; при `screenshot is not None` — список блоков
     `[{"type":"text","text":…}, {"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}]`
   - anthropic: `client.messages.create(model=config.effective_generation_model, system=prompt,
     max_tokens=1024, messages=[{"role":"user","content": …}])`; скриншот — блок
     `{"type":"image","source":{"type":"base64","media_type":"image/png","data":…}}`
   → checkpoint: один запрос на попытку; бюджеты — вне провайдера ✓; system prompt передаётся
   verbatim ✓
4. Извлечение текста: openai `response.choices[0].message.content`; anthropic
   `message.content[0].text` → checkpoint: обе возвращают `str` ✓
5. Ошибка SDK (`openai.OpenAIError` / `anthropic.AnthropicError`) → `LlmUnavailableError`
   … from error, с именем провайдера → checkpoint: таксономия едина для обоих ✓
6. **Output**: `code: str` — без провайдерных конструкций (налагается prompt'ом) ✓

### Trace: `classify_failure`

1. **Input**: prompt=classification_prompt, step_text, code, error, snapshot, screenshot? ✓
2. Один запрос (модель `effective_classification_model`), ответ — одна строка
   `category | explanation | recommendation` ✓
3. Парсинг: strip → первая непустая строка → split `"|"` на 3 части → strip каждой
   → checkpoint: категория ∈ {rot, product_defect, incurable} ✓
4. Непарсимый/неизвестный вердикт → защитный маппинг в `incurable` («classification unparsable…»)
   → checkpoint: безопасный дефолт — падает громко, никогда не маскирует дефект ✓
5. **Output**: `FailureClassification(category, explanation, recommendation)` ✓

### Trace: `run_step_code`

1. **Input**: `code: str`, `page: PageFacade` ✓
2. `namespace: dict = {}`; `exec(compile(code, "<prettyplay-step>", "exec"), namespace)`
   → checkpoint: изолированный namespace, без записи в `sys.modules` ✓
3. `fn = namespace["step"]` — единственный callable фиксированной формы
   → checkpoint: имя фиксировано prompt'ом генерации ✓
4. `fn(page)` — исключение из кода шага пробрасывается как есть
   → checkpoint: no swallow, no retry, no LLM, no network ✓
5. **Output**: None; side effect — действия на странице ✓

### Trace: `StepGenerator.generate` / `regenerate`

1. **Input**: identity, step_text, previous_steps, page (+ existing_code, error для regenerate) ✓
2. Цикл попыток (нумерация с 1):
   - бюджет: generate → `try_generation(identity)`; regenerate → `try_healing(identity)`;
     отказ → `IncurableStepError(step_text, reason="generation|healing attempt budget exhausted",
     recommendation="…")` → checkpoint: исчерпание = неизлечимость, не бесконечный цикл ✓
   - `emit("on_generation_started", {"step_text": step_text, "attempt": n})` ✓
   - сборка запроса: snapshot=`page.aria_snapshot()`; screenshot при `config.send_screenshots`;
     `page_api` = замороженная строка поверхности фасада (см. Algorithm Design) ✓
   - запрос: первая попытка — `existing_code=None, error=None`; каждая повторная — это
     regeneration-request: передаются упавший кандидат и его свежая ошибка
     → checkpoint: трактовка согласована с контрактом провайдера («non-empty only on
     regeneration requests») — повтор попытки с упавшим кандидатом и есть regeneration request ✓
   - `run_step_code(candidate, page)`: успех → `CachedStep(identity, candidate,
     created_at=date.today().isoformat())` → `cache.save` → return; неуспех → короткое
     описание ошибки → следующая итерация ✓
   - `LlmUnavailableError` из провайдера → немедленный проброс, без повтора
     → checkpoint: провайдер вне цикла повторов ✓
3. **Output**: `CachedStep` (сохранён) либо возбуждение таксомии ✓

### Trace: `StepHealer.heal`

1. **Input**: step, error, previous_steps, page (после D1) ✓
2. Сборка: `step_text = step.identity.normalized_text`, `code = step.code`, свежий snapshot
   (+screenshot при флаге) ✓
3. `provider.classify_failure(classification_prompt, …)` → `FailureClassification` ✓
4. `emit("on_healing_started", {"step_text": …, "category": …})` ✓
5. Ветвление по category:
   - `product_defect` → `ProductDefectError(step_text, message=explanation)`; кэш нетронут
     → checkpoint: анти-маскировка ✓
   - `incurable` → `IncurableStepError(step_text, reason=explanation, recommendation)` ✓
   - `rot` → `generator.regenerate(identity=step.identity, step_text, previous_steps, page,
     existing_code=step.code, error=error)` → успех → `emit("on_healed", {"step_text": …,
     "explanation": …})` → return healed; исчерпание бюджета внутри → IncurableStepError
     пробрасывается ✓
6. **Output**: `CachedStep` (вылеченный, перезаписан в кэш только после успешного исполнения) ✓

### Trace: `get_runtime` / `PrettyplayRuntime`

1. Модульная глобаль `_runtime`; первый вызов: `load_config(None)` → `PrettyplayRuntime(config)`;
   далее — тот же объект ✓ (повторные вызовы дёшевы)
2. Properties: `config` (eager), `budgets = RunBudgets(config.generation_attempts,
   config.healing_attempts)` (eager), `driver = DriverSession(config)` (лениво, на первый
   `open_page`), `provider = create_provider(config)` (лениво, на первое обращение — но
   construction провайдера не требует ключей, клиент создаётся при первом запросе)
   → checkpoint: конструкция рантайма без кредов ✓
3. `open_page()` → `self.driver.open_context()` ✓; `close()` → `driver.close()` (безопасен при
   незапуске) ✓

### Trace: `PrettyTest` (конструктор / action / assertion / add_hooks / close)

1. **Input**: cache_key (обязателен), cache_path (опционален) ✓
2. `runtime = get_runtime()`; `reporter = StepReporter(hooks=[])`; `cache = StepCache(
   runtime.config, cache_path, reporter)`; `generator = StepGenerator(runtime.config,
   runtime.provider, cache, runtime.budgets, reporter)`; `healer = StepHealer(runtime.config,
   runtime.provider, generator, cache, runtime.budgets, reporter)`; `executor = StepExecutor(
   cache_key, cache, generator, healer, runtime.budgets, reporter)`
   → checkpoint: все сигнатуры сходятся ✓; обращение к `runtime.provider` здесь безопасно —
   клиент ленивый ✓
3. Страница — лениво: первый `action`/`assertion` → `runtime.open_page()` ✓
4. `action(text)` → `execute(text, "action", page)`; `assertion(text)` → `execute(text,
   "assertion", page)` ✓
5. `add_hooks(hooks)` → append в список reporter'а (до первого шага — lifecycle.md) ✓
6. `close()` / `__exit__` → `page.close()` если открыта; рантайм жив ✓; порядок тестов не влияет
   (пер-тестовых глобалей нет, контексты изолированы) ✓

### Trace: `StepExecutor.execute`

1. `emit("on_step_started", …)` ✓
2. `identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
   normalized_text=normalize_step_text(step_text))` ✓
3. `cached = cache.load(identity)`:
   - hit → `run_step_code(cached.code, page)` → успех → шаг 6; сбой → `healer.heal(cached,
     error=short(exc), previous_steps=self._scenario, page)` → вылечен → шаг 6
     → checkpoint: кэш-путь без LLM ✓ (load + run_step_code не трогают провайдер)
   - miss → `generator.generate(identity, step_text, previous_steps=self._scenario, page)`
     → checkpoint: previous_steps передаются и в генерацию, и в лечение (D1) ✓
4. Шаг 6: `self._scenario.append(step_text)` — оригинальное предложение, как написано инженером
   (читаемость контекста для следующей генерации) ✓
5. `emit("on_step_passed", …)` ✓
6. Возбуждение (любой вид) → `emit("on_step_failed", {"step_text", "step_type", "error":
   short})` → проброс того же вида ✓

**Документированная интерпретация (не дефект).** Требование executor'а «An assertion step
surfaces a legitimately failed expectation as the product defect failure» выполняется
механизмом шага 4 алгоритма — классификацией на кэш-пути (стационарный режим прогона из кэша).
Точная граница применимости: **шаг подпадает под классификацию (и значит под ProductDefectError)
только после первой успешной генерации и сохранения в кэш**. Шаг, который ни разу не
сгенерировался, — во всех прогонах, не только в первом, — даёт `IncurableStepError` и никогда
`ProductDefectError`: на пути промаха различить «сломанный кандидат» и «законно не оправдавшееся
ожидание» без классификации невозможно, контракт генератора явно требует `IncurableStepError`
при исчерпании бюджета, а в кэш попадают только успехи (следующий прогон получает свежий бюджет
и снова промахивается). MVP-stance: тесты пишутся против работающего функционала — дефектная
регрессия ловится классификацией в стационарном режиме; врождённо сломанное ожидание выражается
неизлечимостью (громко, без маскировки). Тексты контрактов не противоречат друг другу при этом
прочтении: «легитимность» ожидания определяется только классификацией, которая контрактом
существует исключительно для упавших кэшированных шагов.

---

## Algorithm Design

### `Config` (config/models.py)

**Responsibility**: валидированные настройки проекта — единственный источник неизменяемой части.

**Algorithm:**
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

**Errors:** `pydantic.ValidationError` — на этапе загрузки; потребитель видит имя невалидной настройки.

**Edge Cases:** пустые строки — легальны (фолбэки/дефолты); `None` не используется (явная
отсутствующность выражается пустой строкой, per conventions).

### `load_config` (config/loader.py)

**Responsibility**: загрузка `[tool.prettyplay]` из pyproject.toml с env-оверрайдами.

**Algorithm:**
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

**Errors:** отсутствие pyproject.toml при авто-поиске → громкая ошибка «pyproject.toml not
found»; ValidationError пробрасывается с контекстом пути.

**Edge Cases:** секции нет → все дефолты; env-строки коэрсятся pydantic ("3"→int, "false"→bool);
пустая env-переменная str-поля легальна, пустая env-переменная int/bool-поля — громкая
ValidationError с именем настройки;
обязанность «never read LLM API keys from any file» — в функции нет чтения чего-либо, кроме
указанного TOML.

### `StepHooks` (reporting/hooks.py)

**Responsibility**: тонкий callback-контракт; база с no-op реализациями всех 8 событий.

**Algorithm:** класс с методами `on_step_started(step_text, step_type)`,
`on_step_passed(step_text, step_type)`, `on_step_failed(step_text, step_type, error)`,
`on_generation_started(step_text, attempt)`, `on_healing_started(step_text, category)`,
`on_healed(step_text, explanation)`, `on_cache_saved(step_text, filename)`,
`on_cache_skipped(step_text, reason)` — тела `pass`.

**Errors:** нет (база).

**Edge Cases:** нет.

### `StepReporter` (reporting/reporter.py)

**Responsibility**: единая точка видимости — логгер `prettyplay` + синхронный fan-out на хуки.

**Algorithm:**
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

**Errors:** исключение хука — WARNING + пропуск; тест не падает из-за хука.

**Edge Cases:** пустой список хуков — только логирование; `emit` синхронен, без очередей.

### `PrettyplayError` + мутации (failures/errors.py)

**Responsibility**: таксономия из трёх различимых видов с общей базой.

**Algorithm:**
```
1. PrettyplayError(Exception): __init__(message) → self.message = message
2. ProductDefectError(PrettyplayError): __init__(step_text, message) → оба атрибута;
   str = f"product defect on step {step_text!r}: {message}"
3. IncurableStepError(PrettyplayError): __init__(step_text, reason, recommendation) →
   три атрибута; str включает все три поля
4. LlmUnavailableError(PrettyplayError): __init__(message) → атрибут message
```

**Errors:** сами являются терминальными видами; не ретраятся библиотекой.

**Edge Cases:** каждое поле в сообщении — требование к рендеру IncurableStepError.

### `DriverSession` (driver/session.py)

**Responsibility**: владелец жизненного цикла Playwright sync-драйвера и браузера на прогон.

**Algorithm:**
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

**Errors:** ошибки Playwright пробрасываются как есть (инфраструктура запуска — вне таксономии
LLM; браузерная недоступность видна напрямую).

**Edge Cases:** headless по умолчанию (`launch()`); повторный `close()` — no-op.

### `PageFacade` / `LocatorFacade` (driver/page.py)

**Responsibility**: узкий стабильный фасад страницы и элемента — единственная страница-API
сгенерированного кода; backward-compatibility контракт (расширять, не переименовывать).

**Algorithm:**
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

**Errors:** неоправдавшееся ожидание → `AssertionError` от `expect(...)` (идёт в классификацию);
таймауты действий → `playwright.Error` (тоже описание сбоя для классификации).

**Edge Cases:** никаких `time.sleep`; фасад не отдаёт сырые объекты Playwright (возвраты —
str / bytes / LocatorFacade).

### `normalize_step_text` (cache/text.py)

**Responsibility**: нормализация предложения шага для адресации.

**Algorithm:**
```
1. s = unicodedata.normalize("NFC", text)
2. s = s.strip()
3. s = re.sub(r"\s+", " ", s)
4. RETURN s.casefold()
```

**Errors:** нет (чистая функция).

**Edge Cases:** пустая строка → пустая; мультибайтовые языки — NFC+casefold стабильны; разные
языки остаются разными шагами.

### `StepIdentity` / `CachedStep` (cache/models.py)

**Responsibility**: адрес шага (+детерминированное имя файла) и единица кэша в памяти.

**Algorithm:**
```
StepIdentity (BaseModel, kw_only): cache_key: str, step_type: str, normalized_text: str
  filename (cached_property):
    identity_string = "\x1f".join((cache_key, step_type, normalized_text))
    RETURN hashlib.sha256(identity_string.encode("utf-8")).hexdigest() + ".py"

CachedStep (BaseModel, kw_only): identity: StepIdentity, code: str, created_at: str
```

**Errors:** нет.

**Edge Cases:** разделитель `\x1f` (Unit Separator) делает конкатенацию однозначной — компоненты
не могут «схлопнуться» в одну и ту же строку разными разбиениями.

### `StepCache` (cache/store.py)

**Responsibility**: репозиторий шагов: адресация, атомарные записи, read-only режим.

**Algorithm:**
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
     code = text от первого "\ndef step(" (с него включительно)
     IF (CACHE_KEY, STEP_TYPE) != (identity.cache_key, identity.step_type)
        или STEP_TEXT != identity.normalized_text: RETURN None   # защитный промах
     RETURN CachedStep(identity=identity, code=code, created_at=CREATED_AT)
   EXCEPT (ValueError, SyntaxError, KeyError, IndexError, OSError): RETURN None
   # невалидный заголовок/литерал, отсутствие любого поля метаданных или хвоста def step(,
   # нечитаемый файл — повреждение кэша никогда не калечит прогон
   # (контракт: «The cache is always read, in every environment»)
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

**Errors:** ни одна ошибка записи не роняет прогон (best-effort); чтение всегда работает.

**Edge Cases:** конкурентные писатели одного шага — последний побеждает, файл не калечится
(атомарный replace); ручная правка файла с расхождением метаданных → защитный промах (регенерация);
повреждённый/обрезанный/нечитаемый файл (любая структурная ошибка разбора) → защитный промах —
кэш всегда читается, сбой одного файла не роняет прогон.

### `RunBudgets` (cache/budgets.py)

**Responsibility**: пер-ранний реестр попыток генерации/лечения на шаг.

**Algorithm:**
```
1. __init__(generation_limit, healing_limit): два dict[str, int] (ключ = identity.filename)
2. try_generation(identity):
   used = self._gen.get(key, 0)
   IF used >= self._generation_limit: RETURN False
   self._gen[key] = used + 1; RETURN True
3. try_healing — симметрично с self._heal / self._healing_limit
```

**Errors:** нет.

**Edge Cases:** бюджеты не сбрасываются между тестами (один процесс — один реестр); xdist-воркеры
= отдельные процессы = отдельные реестры (задокументированное поведение); ничего не персистится.

### `LlmProvider` / `OpenAiProvider` / `AnthropicProvider` (llm/*)

**Responsibility**: единый LLM-порт: генерация кода шага и классификация сбоя; два
взаимозаменяемых SDK-реализации в полном паритете.

**Algorithm (общий каркас обоих провайдеров):**
```
1. __init__(config): self._config; self._client = None
2. _get_client() (лениво):
   key = os.environ.get("OPENAI_API_KEY" | "ANTHROPIC_API_KEY")
   IF not key: raise LlmUnavailableError("llm unavailable: <provider>: <ENV_VAR> is not set")
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
5. Обёртка запросов: except <SDK base error> as e:
   raise LlmUnavailableError(f"llm unavailable: <provider> request failed") from e
```

`build_user_content` — единый для обоих провайдеров формат полей (STEP, PREVIOUS STEPS,
PAGE SNAPSHOT, PAGE API, CODE, ERROR — последние два только регенерационные запросы);
мультимодальная разница — только в обёртке контент-блоков каждого SDK (см. Code Stack Trace).

**Errors:** `LlmUnavailableError` — единственный вид сбоя провайдера (connectivity, timeout,
rate limit, auth, отсутствие ключа); называет провайдера.

**Edge Cases:** пустой ответ модели → трактуется как непарсимый (классификация) / как
негодный кандидат (генерация — код скомпилируется/исполнится и упадёт → повтор по бюджету).

### `create_provider` (llm/provider.py)

**Algorithm:**
```
IF config.provider == "openai":    RETURN OpenAiProvider(config)
ELIF config.provider == "anthropic": RETURN AnthropicProvider(config)
ELSE: raise ValueError("unsupported provider {config.provider!r}: expected one of openai, anthropic")
```

### `run_step_code` (engine/execution.py)

**Responsibility**: исполнение кода шага фиксированной формы против фасада страницы.

**Algorithm:**
```
1. namespace: dict[str, object] = {}
2. exec(compile(code, "<prettyplay-step>", "exec"), namespace)
3. fn = namespace["step"]        # фиксированное имя из generation_prompt
4. fn(page)                      # исключения — наружу как есть
```

**Errors:** любое исключение тела шага пробрасывается без проглатывания и повторов.

**Edge Cases:** выполняется только код из генерации/кэша (единственный источник вызовов —
движок); модуль не регистрируется в `sys.modules`; сетей, кроме самой страницы, нет.

### `StepGenerator` (engine/generator.py)

**Responsibility**: генерация работающего кода шага с исполнением кандидатов на живой странице.

**Algorithm:**
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

**Errors:** `LlmUnavailableError` — сквозной немедленный проброс (не ловится в цикле);
исчерпание — `IncurableStepError`; сбой кандидата — повтор с кодом и ошибкой.

**Edge Cases:** максимум `generation_attempts` (регенерация — `healing_attempts`) запросов на
шаг на прогон; каждый повтор = regeneration-request (несёт существующий код и ошибку).

### `StepHealer` (engine/healer.py)

**Responsibility**: классификация сбоя кэшированного шага, регенерация rot, анти-маскировка дефекта.

**Algorithm:**
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

**Errors:** как в ветвлении; исчерпание бюджета регенерации всплывает из generator как
`IncurableStepError`.

**Edge Cases:** вылеченный код заменяет кэшированный только после успешного исполнения
(гарантия generator); провайдер недоступен → `LlmUnavailableError` со стадии классификации.

### `PrettyTest` (scenario.py)

**Responsibility**: главный объект интегратора — один на тест; владеет адресацией кэша и
изолированным контекстом браузера теста; цикл шагов делегирован executor'у.

**Algorithm:**
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

**Errors:** сбои шагов пробрасываются по виду (таксономия).

**Edge Cases:** конструкция дешева (браузер и страница ленивы); кросс-тестового состояния нет.

### `StepExecutor` (executor.py)

**Responsibility**: владелец цикла шага: hit → исполнить; miss → сгенерировать; сбой кэша → лечить.

**Algorithm:**
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

**Errors:** виды таксономии пробрасываются с предварительным `on_step_failed`.

**Edge Cases:** сценарный контекст пер-тестовый (живёт в executor'е); кэш-путь без LLM.

### `PrettyplayRuntime` / `get_runtime` (runtime.py)

**Responsibility**: composition root раннего масштаба — всё общее для тестов, ничего пер-тестового.

**Algorithm:**
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

**Errors:** нет своих; всё лениво.

**Edge Cases:** отсутствие ключей LLM не мешает старту и кэш-прогонам (клиент создаётся при
первом запросе); `__init__.py` корня реэкспортирует публичный фасад:
`from .scenario import PrettyTest; from .executor import StepExecutor; from .runtime import
PrettyplayRuntime, get_runtime` (+ `__all__`), обеспечивая `python -c "from prettyplay import
PrettyTest"`.

---

## Cross-cutting Concerns

- **Error handling**: три вида сбоев (`ProductDefectError`, `IncurableStepError`,
  `LlmUnavailableError`) с общей базой `PrettyplayError`; сбои хуков и записи кэша никогда не
  роняют прогон (WARNING + продолжение); исключения кода шага пробрасываются как есть;
  `LlmUnavailableError` — без повторов. Каждое сообщение actionable: шаг, причина, рекомендация.
- **Logging**: единственный логгер `logging.getLogger("prettyplay")`; события — стабильные
  имена (= имена хуков), lowercase, контекст через `extra`; уровни: жизненный цикл — INFO,
  `on_cache_skipped` и сбой хука — WARNING; секреты не логируются никогда (в т.ч. payload
  провайдера и ключи).
- **Validation**: конфигурация — при загрузке (Literal/PositiveInt, громко, с именем поля);
  файлы кэша — при чтении (соответствие метаданных identity, защитный промах); вердикт
  классификации — при парсинге (неизвестное → безопасный incurable); код шага — компиляцией и
  исполнением в цикле генерации.
- **Caching**: репозиторий шагов — один `.py`-файл на шаг, адрес = sha256(тройка), атомарные
  записи (tmp + `os.replace`), best-effort запись, всегда доступное чтение; бюджеты попыток —
  in-memory на процесс; провайдер/драйвер/страницы — ленивые singleton'ы своей области.
- **Concurrency**: библиотека однопоточна (sync Playwright); блокировок нет; конкурентные
  писатели одного файла шага безопасны атомарным replace (последний побеждает);
  `RunBudgets` и `_runtime` без локов — в рамках процесса это корректно; pytest-xdist изолирован
  процессами (отдельные рантаймы и бюджеты — задокументированное поведение).

---

## Usages Analysis

### `conventions`
- **What it provides**: обязательные правила python-кода и тестов (3.10+, относительные
  импорты внутри пакета, pydantic kw_only+пустые дефолты, logging с контекстом, Google-docstring,
  ruff, структура tests/, моки только на внешних границах).
- **Where used**: все 8 клеток (глобальные аннотации).
- **Why chosen**: проектный стандарт; фасад-проверка `from prettyplay import PrettyTest`.
- **How exactly**: `logging.getLogger` с `extra`; `tmp_path` для файловых тестов; тесты зеркалят
  структуру: `prettyplay/cache/store.py` → `tests/cache/test_store.py`.

### `pydantic`
- **What it provides**: паттерны моделей v2 (`ConfigDict(kw_only=True)`, пустые дефолты) и
  загрузка TOML с tomli-фолбэком для 3.10.
- **Where used**: config (`Config`, `load_config`); модельные клетки (StepIdentity, CachedStep,
  FailureClassification).
- **Why chosen**: требования conventions к моделям данных + стандартный TOML-путь.
- **How exactly**: `model_config = ConfigDict(kw_only=True)`; `tomllib`/`tomli` по
  `sys.version_info`; секция `data.get("tool", {}).get("prettyplay", {})`.

### `playwright`
- **What it provides**: sync-API lifecycle, матрица браузеров, локаторы с auto-wait, a11y-снимок,
  скриншот.
- **Where used**: driver (вся клетка); engine —语义 через `facade`.
- **Why chosen**: единственный драйвер MVP (sync-only).
- **How exactly**: `sync_playwright().start()` для долгоживущей сессии; словарь движков
  `{chromium, firefox, webkit}`; `page.locator("body").aria_snapshot()`; `expect(...)` для
  ожиданий; никаких `time.sleep` в шагах.

### `openai` / `anthropic`
- **What it provides**: паттерны вызовов SDK, ключи из env, маппинг ошибок SDK →
  `LlmUnavailableError`, паритет операций.
- **Where used**: llm (`OpenAiProvider`, `AnthropicProvider`).
- **Why chosen**: два поддерживаемых провайдера MVP.
- **How exactly**: `OpenAI(api_key=os.environ[...])` / `anthropic.Anthropic(...)`;
  `chat.completions.create` / `messages.create(system=..., max_tokens=1024)`; один запрос на
  попытку; `OpenAIError`/`AnthropicError` → `LlmUnavailableError ... from error`.

### `generation_prompt` (inline, engine)
- **What it provides**: системный промпт генерации — фиксирует форму ответа (один блок, `def
  step(page) -> None`), входы (STEP/PREVIOUS STEPS/PAGE SNAPSHOT/SCREENSHOT/PAGE API/CODE/ERROR)
  и правила (только поверхность фасада, без импортов, без задержек).
- **Where used**: `StepGenerator.generate/regenerate` → `provider.generate_step_code(prompt=…)`.
- **Why chosen**: inline — специфично клетке engine, вне её бессмысленно.
- **How exactly**: передаётся verbatim как system-сообщение каждого запроса генерации.

### `classification_prompt` (inline, engine)
- **What it provides**: системный промпт классификации — ответ одной строкой
  `category | explanation | recommendation`, категории rot/product_defect/incurable.
- **Where used**: `StepHealer.heal` → `provider.classify_failure(prompt=…)`.
- **Why chosen**: inline, клетко-специфично.
- **How exactly**: verbatim как system-сообщение; парсинг первой непустой строки по `|`.

### Imported Usages
- `hooks` from `prettyplay/reporting` — контракт событий для cache (события записи кэша) и
  корня (add_hooks); путь `prettyplay/reporting/.usages/hooks.md`.
- `taxonomy` from `prettyplay/failures` — виды сбоев, пробрасываемые методами шагов корня;
  путь `prettyplay/failures/.usages/taxonomy.md`.
- `generation`, `healing` from `prettyplay/engine` — циклы движка, которым делегирует
  `StepExecutor`; пути `prettyplay/engine/.usages/{generation,healing}.md`.
- `facade` from `prettyplay/driver` — единый источник поверхности PAGE API для запросов
  генерации; путь `prettyplay/driver/.usages/facade.md`.
- `classification` from `prettyplay/llm` — категории решения лечения; путь
  `prettyplay/llm/.usages/classification.md`.

---

## `.usages/` Update

### Cell: `prettyplay/engine`

#### Existing Files — Consistency
- **`healing.md`** → `prettyplay/engine/.usages/healing.md`
  - Status: обновлён на этой стадии (одобрено пользователем)
  - Updates applied: пример `heal(...)` теперь передаёт `previous_steps=[…]` (следствие D1);
    правило бюджетов переформулировано — «Generation and healing attempts live in one
    run-scoped registry with separate per-step limits (default 3 and 2)» вместо двусмысленного
    «share the per-step run budget».
- **`generation.md`** → актуален (сигнатура `generate`, цикл, бюджеты, фиксированная форма).

### Cell: `prettyplay/reporting`

#### Existing Files — Consistency
- **`hooks.md`** → `prettyplay/reporting/.usages/hooks.md`
  - Status: обновлён на этой стадии (одобрено пользователем)
  - Updates applied: «Payload values are plain strings; the attempt counter of
    on_generation_started is an int» (следствие D2).

### Остальные клетки

- `prettyplay/.usages/steps.md`, `lifecycle.md` — актуальны (API `PrettyTest`, композиция,
  виды сбоев соответствуют контрактам).
- `prettyplay/config/.usages/configuration.md` — актуален (схема, 10 env-оверрайдов, дефолты).
- `prettyplay/failures/.usages/taxonomy.md` — актуален (после D3 обращение
  `info.value.recommendation` теперь в контракте).
- `prettyplay/driver/.usages/facade.md` — актуален (поверхность = PageFacade/LocatorFacade).
- `prettyplay/cache/.usages/addressing.md`, `storage.md`, `budgets.md` — актуальны.
- `prettyplay/llm/.usages/providers.md`, `classification.md` — актуальны.

#### New Files (if any)
Не требуются: существующая доменная разбивка покрывает все сущности; правки внутри доменов.

---

## Test Stack Trace

### General Setup

- Структура зеркальная: `tests/<клетка>/test_<module>.py`; каждый каталог с `__init__.py`;
  локальные фикстуры в `tests/<клетка>/conftest.py`. Тесты корневых модулей — прямо в `tests/`.
- Моки только на внешних границах: SDK (`openai`/`anthropic` клиенты), Playwright (драйвер),
  время отсутствует (кэш-события детерминированы). Файловые тесты — только `tmp_path`.
- Провайдер в engine/root-тестах заменяется stub-объектом с сигнатурами `LlmProvider`
  (`generate_step_code`, `classify_failure`), страница — fake-объектом с методами фасада.

### Source File Registry

| Клетка | Файлы под тестом |
|---|---|
| config | models.py, loader.py |
| reporting | hooks.py, reporter.py |
| failures | errors.py |
| driver | session.py, page.py |
| cache | text.py, models.py, store.py, budgets.py |
| llm | provider.py, openai_provider.py, anthropic_provider.py, models.py |
| engine | execution.py, generator.py, healer.py |
| prettyplay | scenario.py, executor.py, runtime.py |

---

### Positive Tests

#### `test_config_defaults_valid`

**Setup**: ничего (чистая модель).

**Input**: `Config()`.

**Trace**:
```
Config()
  → pydantic валидация дефолтов      # provider/browser Literal, attempts PositiveInt
  → поля установлены
  → effective_generation_model       # generation_model="" → fallback
    returns: Config.model
```

**Assertions**:
```
config.provider == "openai"
config.browser == "chromium"
config.generation_attempts == 3 and config.healing_attempts == 2
config.send_screenshots is False
config.effective_generation_model == config.model == ""
```

**Sufficiency**: фиксирует контракт дефолтов и фолбэка моделей — регрессия смены дефолтов MVP.

---

#### `test_load_config_reads_section_and_env_overrides`

**Setup**: `tmp_path/pyproject.toml`:
```toml
[tool.prettyplay]
provider = "openai"
browser = "chromium"
model = "gpt-5"
```
`monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")`; `monkeypatch.setenv("PRETTYPLAY_GENERATION_ATTEMPTS", "5")`.

**Input**: `load_config(pyproject_path=str(tmp_path / "pyproject.toml"))`.

**Trace**:
```
load_config(path)
  → tomllib.load                      # секция прочитана
  → env override browser="firefox", generation_attempts="5"
  → Config(**merged)                  # коэрсия "5"→5
  → cache_root пуста → tmp_path/.prettyplay/cache/
```

**Assertions**:
```
config.model == "gpt-5"
config.browser == "firefox"            # env перекрывает TOML
config.generation_attempts == 5        # str→int коэрсия
config.cache_root == str(tmp_path / ".prettyplay" / "cache")
```

**Sufficiency**: ядро загрузчика — TOML + env + разрешение дефолтного корня кэша.

---

#### `test_emit_dispatches_event_to_hooks_in_order`

**Setup**: два хука-рекордера `RecordingHook(StepHooks)` с общим списком `calls`; reporter =
`StepReporter(hooks=[h1, h2])`.

**Input**: `reporter.emit("on_step_started", {"step_text": "открыть страницу", "step_type": "action"})`.

**Trace**:
```
emit(...)
  → logger.info("on_step_started", extra={...})
  → h1.on_step_started(step_text=..., step_type=...)   # kwargs
  → h2.on_step_started(...)
```

**Assertions**:
```
calls == [("h1", "on_step_started", "открыть страницу", "action"),
          ("h2", "on_step_started", "открыть страницу", "action")]
caplog: одна запись INFO, logger == "prettyplay", msg == "on_step_started",
        record.step_text == "открыть страницу"
```

**Sufficiency**: механика emit — порядок fan-out, имена событий = имена методов, контекст в логе.

---

#### `test_open_context_lazy_launch_single_browser`

**Setup**: `mock.patch("prettyplay.driver.session.sync_playwright")` → fake pw: `pw().start()`
возвращает объект с `chromium/firefox/webkit`, каждый `.launch()` пишет в `launches`;
`new_context()` → контекст с `new_page()`.

**Input**: `session = DriverSession(Config(browser="chromium"))`; `session.open_context()` ×2.

**Trace**:
```
DriverSession(config)           # ничего не запущено
  → open_context() #1           # lazy: start + chromium.launch() (1 раз) + new_context + new_page
  → open_context() #2           # браузер уже есть: только new_context + new_page
```

**Assertions**:
```
после конструктора: pw.start не вызывался
launches == 1
два результата — разные PageFacade; контекстов создано 2
```

**Sufficiency**: «один браузер на прогон, изолированный контекст на тест» и ленивость запуска.

---

#### `test_normalize_step_text_equivalence`

**Setup**: нет.

**Input**: `normalize_step_text("  Нажать   Войти ")`, `normalize_step_text("нажать войти")`.

**Trace**:
```
"  Нажать   Войти " → NFC → strip → collapse → casefold → "нажать войти"
"нажать войти"      → тот же пайплайн → "нажать войти"
```

**Assertions**:
```
normalize_step_text("  Нажать   Войти ") == normalize_step_text("нажать войти") == "нажать войти"
normalize_step_text("Нажать Войти") != normalize_step_text("Click Login")
```

**Sufficiency**: идентичность шага из ADR-семантики адресации — «равные предложения = один шаг».

---

#### `test_identity_filename_deterministic_and_discriminating`

**Setup**: нет.

**Input**: две идентичные и две различающиеся тройки.

**Trace**:
```
StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename
StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename   # тот же digest
StepIdentity(cache_key="k", step_type="assertion", normalized_text="нажать войти").filename # другой digest
StepIdentity(cache_key="k2", step_type="action", normalized_text="нажать войти").filename   # другой digest
```

**Assertions**:
```
f1 == f2; f1 != f3; f1 != f4
f1.endswith(".py") and len(digest-часть) == 64
```

**Sufficiency**: адресация — одинаковая тройка → один файл, любое отличие → другой.

---

#### `test_save_load_roundtrip_via_file`

**Setup**: `tmp_path`; `Config(cache_root=str(tmp_path))`; reporter с рекордером;
`cache = StepCache(config, "checkout", reporter)`; `identity = StepIdentity(cache_key="login-flow",
step_type="action", normalized_text="открыть страницу логина")`.

**Input**: `cache.save(CachedStep(identity=identity, code="def step(page) -> None:\n    page.open('https://x')\n", created_at="2026-09-07"))`; затем `cache.load(identity)`.

**Trace**:
```
save(step)
  → tmp в tmp_path/checkout/.tmp-*.py → os.replace → checkout/<digest>.py
  → emit on_cache_saved(filename=<digest>.py)
load(identity)
  → чтение файла → заголовок STEP_TEXT/CACHE_KEY/STEP_TYPE/CREATED_AT → хвост def step(...)
  → соответствие identity ✓
```

**Assertions**:
```
loaded is not None
loaded.identity == identity
loaded.code.startswith("def step(")
loaded.created_at == "2026-09-07"
файл: text.startswith("STEP_TEXT =") и "def step(" в text
recorded: ("on_cache_saved", {"filename": identity.filename})
caplog: запись INFO "on_cache_saved" от логгера "prettyplay"; record.ctx_filename == identity.filename
import файла через importlib.util.spec_from_file_location("cached_step", path)
  + module_from_spec + exec_module успешен (валидный модуль; имя файла-дайджеста
  не обязано быть идентификатором — load идёт текстом, не по имени модуля)
```

**Sufficiency**: полный цикл хранилища — формат файла, атомарность вызова, восстановление шага.

---

#### `test_budgets_separate_pools_shared_per_identity`

**Setup**: `budgets = RunBudgets(generation_limit=1, healing_limit=1)`; `identity` и `identity2`.

**Input**: `try_generation(identity)` ×2; `try_healing(identity)`; `try_generation(identity2)`.

**Trace**:
```
try_generation(id)  → True (0→1)
try_generation(id)  → False (лимит 1)
try_healing(id)     → True (отдельный пул)
try_generation(id2) → True (другой шаг — свой бюджет)
```

**Assertions**:
```
результаты: [True, False, True, True]
```

**Sufficiency**: раздельные лимиты; бюджет на шаг (не на тест) — общий для всех тестов прогона.

---

#### `test_create_provider_selects_by_config`

**Setup**: `Config(provider="anthropic", model="claude-sonnet-4-5")` (env-ключей нет — не нужен).

**Input**: `create_provider(config)`.

**Trace**:
```
create_provider → "anthropic" → AnthropicProvider(config)
```

**Assertions**:
```
isinstance(provider, AnthropicProvider)
isinstance(provider, LlmProvider)   # контракт порта
```

**Sufficiency**: выбор провайдера — решение конфигурации; конструкция без ключей.

---

#### `test_openai_provider_error_maps_to_llm_unavailable`

**Setup**: `mock.patch` клиента SDK: `chat.completions.create` поднимает `OpenAIError("timeout")`;
env `OPENAI_API_KEY=test`.

**Input**: `OpenAiProvider(Config(model="gpt-5")).generate_step_code(prompt="p", step_text="s",
previous_steps=[], snapshot="- snap", screenshot=None, page_api="page.open(...)", existing_code=None, error=None)`.

**Trace**:
```
generate_step_code → ленивый клиент → create(...) → OpenAIError
  → raise LlmUnavailableError("llm unavailable: openai request failed") from error
```

**Assertions**:
```
pytest.raises(LlmUnavailableError); "openai" in str(excinfo.value)
isinstance(excinfo.value, PrettyplayError)
```

**Sufficiency**: маппинг инфраструктурного сбоя SDK в таксономию — без повторов на уровне провайдера.

---

#### `test_missing_api_key_surfaces_on_first_request`

**Setup**: `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`.

**Input**: `provider = OpenAiProvider(Config())` (не падает); затем вызов `classify_failure(...)`.

**Trace**:
```
OpenAiProvider(Config())   # конструктор не читает env
classify_failure(...)      # первый запрос → _get_client → ключа нет
  → LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")
```

**Assertions**:
```
конструкция успешна (нет исключения)
pytest.raises(LlmUnavailableError) на первом запросе; "OPENAI_API_KEY" in str(...)
```

**Sufficiency**: требование рантайма — старт без кредов, сбой только на генерации/классификации.

---

#### `test_run_step_code_executes_fixed_form`

**Setup**: fake page с записью вызовов.

**Input**: `run_step_code("def step(page) -> None:\n    page.open('https://example.com')\n", page)`.

**Trace**:
```
compile(code) → namespace {} → namespace["step"] → step(page)
  → page.open("https://example.com")
```

**Assertions**:
```
page.calls == [("open", "https://example.com")]
```

**Sufficiency**: механизм исполнения фиксированной формы — компиляция, изоляция, вызов.

---

#### `test_generate_success_stores_and_reports_attempt`

**Setup**: stub-провайдер: `generate_step_code` возвращает рабочий код для fake page; кэш на
`tmp_path`; рекордер событий; `budgets = RunBudgets(3, 2)`; generator = StepGenerator(...).

**Input**: `generator.generate(identity, "открыть страницу", [], page)`.

**Trace**:
```
generate → try_generation ✓ → on_generation_started(attempt=1) → aria_snapshot
  → provider.generate_step_code(existing_code=None, error=None)
  → run_step_code ✓ → CachedStep → cache.save → on_cache_saved
```

**Assertions**:
```
step.code == код заглушки; step.identity == identity
provider.calls == 1; первая попытка без existing_code/error
recorded on_generation_started: attempt == 1 (int)
recorded on_cache_saved с filename == identity.filename
```

**Sufficiency**: счастливый путь генерации — хранение, событие с int-попыткой, чистый первый запрос.

---

#### `test_generate_retries_with_existing_code_then_succeeds`

**Setup**: stub-провайдер: первый ответ — код, падающий на fake page (`page.find_by_role(...)`
бросает AssertionError), второй — рабочий; рекордер.

**Input**: `generator.generate(identity, "нажать Войти", [], page)`.

**Trace**:
```
attempt 1: код A → run_step_code → AssertionError → error=short
attempt 2: запрос с existing_code=A, error="..." → код B → run_step_code ✓
  → cache.save → return
```

**Assertions**:
```
provider.calls == 2
второй вызов: existing_code == A и error содержит текст сбоя
recorded on_generation_started ×2 (attempt 1, attempt 2)
```

**Sufficiency**: цикл повтора — свежая ошибка и упавший кандидат возвращаются провайдеру
(документированная интерпретация regeneration-request).

---

#### `test_heal_rot_regenerates_and_reports_healed`

**Setup**: провайдер-classification → `FailureClassification("rot", "кнопка переименована",
"проверить шаг")`; регенерация через stub generator-объект (рекордер: regenerate(...) →
возвращает вылеченный CachedStep); healer = StepHealer(config, provider, generator, cache,
budgets, reporter).

**Input**: `healer.heal(step=failed_step, error="element not found", previous_steps=["открыть"], page=page)`.

**Trace**:
```
heal → classify_failure(classification_prompt, code=failed_step.code, error=...)
  → verdict rot → on_healing_started(category="rot")
  → generator.regenerate(identity, step_text, previous_steps, page,
        existing_code=failed_step.code, error="element not found")
  → on_healed(explanation="кнопка переименована") → return healed
```

**Assertions**:
```
возвращён вылеченный шаг
regenerate вызван ровно 1 раз с existing_code=failed_step.code и previous_steps=["открыть"]
recorded: on_healing_started(category="rot"), on_healed(explanation="кнопка переименована")
cache.save не вызван напрямую healer'ом (пишет generator после успешного исполнения)
```

**Sufficiency**: ветка rot — классификация, делегирование регенерации с полным контекстом,
громкое событие излечения.

---

#### `test_get_runtime_is_process_singleton`

**Setup**: изоляция глобали (сброс приватной глобали до/после); `mock.patch` load_config →
фиксированный Config.

**Input**: `get_runtime()` ×2.

**Trace**:
```
get_runtime() #1 → load_config(None) → PrettyplayRuntime → запомнен
get_runtime() #2 → тот же объект
```

**Assertions**:
```
runtime1 is runtime2
load_config вызван ровно 1 раз
```

**Sufficiency**: один рантайм на процесс — конфигурация и бюджеты не пересоздаются.

---

#### `test_action_cached_step_runs_without_llm`

**Setup**: `tmp_path`-кэш с предзаписанным файлом шага (валидный модуль для «открыть страницу
логина»); runtime-глобаль сброшена; env без ключей; провайдер-заглушка, бросающий
`AssertionError("provider must not be called")` при любом вызове (детект нарушения); page
подменена на fake (mock runtime.open_page).

**Input**: `t = PrettyTest("login-flow"); t.action("открыть страницу логина"); t.close()`.

**Trace**:
```
PrettyTest → get_runtime → executor
action → identity → cache.load → hit → run_step_code(code, fake page) ✓
  → on_step_started / on_step_passed; методы провайдера не вызваны, SDK-клиент не создавался
```

**Assertions**:
```
шаг завершился без исключений
recorded: on_step_started, on_step_passed (step_type="action")
провайдер-заглушка не вызвана (кэш-путь без LLM)
```

**Sufficiency**: центральное обещание продукта — кэшированный прогон вообще не требует LLM.

---

#### `test_scenario_context_feeds_next_generation`

**Setup**: кэш пуст; провайдер-заглушка возвращает рабочий код; рекордер предыдущих шагей
в запросах; fake page.

**Input**: `t = PrettyTest("k"); t.action("шаг один"); t.action("шаг два"); t.close()`.

**Trace**:
```
шаг один: miss → generate(previous_steps=[]) ✓
шаг два:  miss → generate(previous_steps=["шаг один"]) ✓
```

**Assertions**:
```
второй запрос провайдера получил previous_steps == ["шаг один"]
первый — []
```

**Sufficiency**: сценарный контекст теста питает следующую генерацию (и, после D1, лечение).

---

### Negative Tests

#### `test_config_invalid_provider_fails_loudly`

**Setup**: нет.

**Input**: `Config(provider="yandex")` (в `pytest.raises(ValidationError)`).

**Trace**:
```
Config(provider="yandex") → Literal-валидация → ValidationError
```

**Assertions**:
```
"provider" в тексте ошибки; перечислены допустимые значения
```

**Sufficiency**: невалидная конфигурация падает громко и actionable на загрузке.

---

#### `test_raising_hook_is_skipped_and_logged`

**Setup**: h1 — хук, бросающий RuntimeError на on_step_passed; h2 — рекордер;
reporter = `StepReporter(hooks=[h1, h2])`; `caplog`.

**Input**: `reporter.emit("on_step_passed", {"step_text": "s", "step_type": "action"})`.

**Trace**:
```
emit → h1.on_step_passed → RuntimeError → logger.warning("hook call failed") → h2 вызван
```

**Assertions**:
```
исключение не пробросилось наружу
h2 получил событие
в caplog есть WARNING от логгера "prettyplay"
```

**Sufficiency**: сбой хука никогда не роняет прогон — но виден в логах.

---

#### `test_generate_budget_exhaustion_raises_incurable`

**Setup**: провайдер всегда возвращает код, падающий на fake page; `RunBudgets(3, 2)`; кэш tmp.

**Input**: `generator.generate(identity, "невозможный шаг", [], page)`.

**Trace**:
```
attempts 1..3: try_generation ✓ → кандидат падает → повтор
4-я итерация: try_generation → False → IncurableStepError
```

**Assertions**:
```
pytest.raises(IncurableStepError)
excinfo.value.reason упоминает бюджет; excinfo.value.recommendation непусто
provider.calls == 3
cache.save не вызван (неудачи не кэшируются)
```

**Sufficiency**: исчерпание бюджета = неизлечимость, а не бесконечный цикл; провайдер не
вызывается сверх лимита.

---

#### `test_generate_provider_unavailable_propagates_immediately`

**Setup**: провайдер-заглушка поднимает `LlmUnavailableError` в каждом вызове; счётчик вызовов.

**Input**: `generator.generate(identity, "шаг", [], page)`.

**Trace**:
```
attempt 1: try_generation ✓ → on_generation_started → provider → LlmUnavailableError → проброс
```

**Assertions**:
```
pytest.raises(LlmUnavailableError)
provider.calls == 1        # никаких повторов на инфраструктурный сбой
budgets: израсходована 1 попытка генерации
```

**Sufficiency**: «no retry on it» — блокировка только генерации/лечения, кэш продолжает жить.

---

#### `test_heal_provider_unavailable_propagates`

**Setup**: stub-провайдер, `classify_failure` поднимает `LlmUnavailableError`; generator-шпион
(рекордер вызовов); кэш-шпион (save не должен вызываться).

**Input**: `healer.heal(failed_step, "err", [], page)`.

**Trace**:
```
heal → сборка входов → provider.classify_failure → LlmUnavailableError → немедленный проброс
  (без регенерации, без ретраев, кэш не тронут)
```

**Assertions**:
```
pytest.raises(LlmUnavailableError)
generator.regenerate не вызван; cache.save не вызван
```

**Sufficiency**: «Blocks only code generation and healing; cached steps keep running» —
инфраструктурный сбой на стадии классификации не маскируется и не ретраится; кэш не
перезаписывается.

---

#### `test_heal_product_defect_raises_and_keeps_cache`

**Setup**: провайдер-classification → `("product_defect", "ожидание не оправдалось", "чинить
продукт")`; кэш-шпион (save не должен вызываться); generator-шпион.

**Input**: `healer.heal(failed_step, "text mismatch", ["шаг"], page)`.

**Trace**:
```
classify → product_defect → on_healing_started(category="product_defect")
  → ProductDefectError(step_text, "ожидание не оправдалось")
```

**Assertions**:
```
pytest.raises(ProductDefectError); issubclass(ProductDefectError, PrettyplayError)
generator.regenerate не вызван; cache.save не вызван
```

**Sufficiency**: анти-маскировка — законный дефект продукта падает громко, ничего не
регенерируется и не перезаписывается.

---

#### `test_heal_incurable_carries_verdict_fields`

**Setup**: провайдер-classification → `("incurable", "текст шага не соответствует реальности",
"переформулируйте шаг")`.

**Input**: `healer.heal(failed_step, "err", [], page)`.

**Trace**:
```
classify → incurable → on_healing_started → IncurableStepError(step_text, reason, recommendation)
```

**Assertions**:
```
pytest.raises(IncurableStepError)
excinfo.value.reason == "текст шага не соответствует реальности"
excinfo.value.recommendation == "переформулируйте шаг"
str(excinfo.value) содержит все три поля
```

**Sufficiency**: неизлечимость переносит вердикт инженеру — actionable сообщение.

---

#### `test_create_provider_unknown_fails_loudly`

**Input**:
```python
config = Config.model_construct(provider="groq")  # валидация обойдена намеренно:
                                                  # Literal иначе не пропустит значение
create_provider(config)
```

**Trace**:
```
Config.model_construct(provider="groq")   # поле проставлено без валидации
create_provider → elif-цепочка не совпала → ValueError со списком поддерживаемых
```

**Assertions**:
```
pytest.raises(ValueError); "openai" и "anthropic" в тексте
```

**Sufficiency**: защита на случай конфигурации, прошедшей мимо валидации Config.

---

#### `test_save_readonly_cache_skips_loudly`

**Setup**: `tmp_path`-каталог, `chmod 0o500` (skipif если запуск под root — root игнорирует
режимы); `os.access` вернёт False; рекордер событий.

**Input**: `cache.save(step)`.

**Trace**:
```
save → writable False → emit on_cache_skipped(reason="read-only cache") → выход без записи
```

**Assertions**:
```
исключений нет; файл не создан
recorded: ("on_cache_skipped", reason="read-only cache")
```

**Sufficiency**: read-only прогон корректен — кэш всегда читается, запись тихо-громко пропускается.

---

#### `test_load_missing_file_returns_none`

**Input**: `cache.load(StepIdentity(cache_key="k", step_type="action", normalized_text="нет такого шага"))`.

**Trace**:
```
load → файл не существует → None
```

**Assertions**:
```
result is None
```

**Sufficiency**: промах кэша — штатная ситуация, а не ошибка.

---

#### `test_load_config_no_pyproject_fails_loudly`

**Setup**: изолированный рабочий каталог без pyproject.toml вверх по дереву
(`monkeypatch.chdir(tmp_path)`; при недетерминированности окружения — `mock.patch` поиска
вверх от cwd).

**Input**: `load_config(pyproject_path=None)`.

**Trace**:
```
load_config → авто-поиск: cwd и все родители → pyproject.toml не найден
  → громкая ошибка «pyproject.toml not found»
```

**Assertions**:
```
pytest.raises с текстом "pyproject.toml not found"
```

**Sufficiency**: контракт авто-поиска — отсутствие файла конфигурации не молчит: инженер
видит actionable-ошибку, а не загадочные дефолты из чужого pyproject.toml.

---

### Edge Case Tests

#### `test_load_config_missing_section_yields_defaults`

**Setup**: `tmp_path/pyproject.toml` без `[tool.prettyplay]` (например, только `[project]`).

**Input**: `load_config(pyproject_path=...)`.

**Trace**:
```
toml → data.get("tool", {}).get("prettyplay", {}) = {} → Config() → дефолты
```

**Assertions**:
```
config.provider == "openai"; config.generation_attempts == 3
```

**Sufficiency**: «a missing section is an empty section» — пустой TOML не ломает запуск.

---

#### `test_normalize_empty_and_whitespace_only`

**Input**: `normalize_step_text("")`, `normalize_step_text("   ")`, `normalize_step_text("\n\t")`.

**Assertions**:
```
все три → ""
```

**Sufficiency**: граничные входы чистой функции — пустые/пробельные предложения дают пустой
нормализованный текст (адрес при этом всё равно уникален тройкой).

---

#### `test_load_metadata_mismatch_treated_as_miss`

**Setup**: в `tmp_path`-кэше файл с digest'ом identity, но вручную изменённым `STEP_TEXT`.

**Input**: `cache.load(identity)`.

**Trace**:
```
load → файл есть → метаданные ≠ identity → защитный промах → None
```

**Assertions**:
```
result is None (шаг будет регенерирован, прогон не падает)
```

**Sufficiency**: ручная правка/повреждение файла кэша не калечит прогон.

---

#### `test_load_corrupt_file_treated_as_miss`

**Setup**: в `tmp_path`-кэше файл с именем `identity.filename`, содержимое — обрывок без
заголовка и без `def step(`: `"garbage not a module"`.

**Input**: `cache.load(identity)`.

**Trace**:
```
load → файл существует → чтение → разбор заголовка не удался (нет полей-констант),
  хвост "\ndef step(" не найден → защитный блок → None
```

**Assertions**:
```
result is None (без исключений; шаг будет регенерирован, прогон не падает)
```

**Sufficiency**: контрактовое «The cache is always read, in every environment» — структурно
повреждённый файл даёт промах, а не краш прогона; регрессия на выброс исключения из load.

---

#### `test_budgets_default_limits_from_config`

**Input**: `RunBudgets(config.generation_attempts, config.healing_attempts)` при `Config()`.

**Trace**:
```
RunBudgets(3, 2): 3× try_generation → True,True,True,False; независимо 2× try_healing
```

**Assertions**:
```
[try_generation(id) for _ in range(4)] == [True, True, True, False]
[try_healing(id) for _ in range(3)] == [True, True, False]
```

**Sufficiency**: стандартные бюджеты MVP 3/2 — инвариант настройки по умолчанию.

---

#### `test_classification_unparsable_defaults_to_incurable`

**Setup**: провайдер-заглушка возвращает мусор ("sorry cannot answer" без `|`).

**Input**: `provider.classify_failure(...)` (уровень провайдера).

**Trace**:
```
парсинг не удался → защитный маппинг → FailureClassification("incurable", "classification
verdict unparsable", …)
```

**Assertions**:
```
classification.category == "incurable"
```

**Sufficiency**: кривой ответ LLM не может замаскировать дефект — безопасный дефолт.

---

#### `test_prettytest_context_manager_closes_page`

**Setup**: runtime-глобаль изолирована; `mock` runtime.open_page → fake page с рекордом close().

**Input**:
```python
with PrettyTest("k") as t:
    t.action("шаг")
```

**Trace**:
```
__enter__ → self; action → open_page (1 раз) → execute ✓
__exit__ → close() → page.close()
```

**Assertions**:
```
page.closed is True; runtime.close не вызван (рантайм жив)
второй with: новая страница, тот же runtime
```

**Sufficiency**: контекст-менеджер закрывает пер-тестовый контекст, не задевая общий рантайм.

---

#### `test_runtime_constructs_without_llm_credentials`

**Setup**: `monkeypatch.delenv` обоих ключей; runtime-глобаль изолирована.

**Input**: `runtime = PrettyplayRuntime(Config(model="gpt-5"))`; чтение `runtime.config`,
`runtime.budgets`.

**Trace**:
```
__init__ → Config, RunBudgets — клиент провайдера не создаётся
provider не запрашивался
```

**Assertions**:
```
конструкция без исключений
runtime.provider ещё не создавался (лениво) — обращение к нему вне теста не требуется
```

**Sufficiency**: прогон без ключей стартует и работает на кэше —_team-workflow CI без секретов.

---

#### `test_incurable_error_message_renders_all_fields`

**Input**: `str(IncurableStepError("шаг", "причина", "рекомендация"))`.

**Assertions**:
```
"шаг" in s and "причина" in s and "рекомендация" in s
ошибка — экземпляр PrettyplayError (единый except на границе suite)
```

**Sufficiency**: требование «the rendered message includes each of them» + единая база таксономии.

---

## Additional Instructions for the Implementation Agent

- Реализовать клетки строго снизу вверх: config → reporting → failures → driver → cache → llm →
  engine → корень; после каждой клетки — `goga lint` и фасад-проверка импорта.
- `prettyplay/__init__.py` — реэкспорт фасада корня (`PrettyTest`, `StepExecutor`,
  `PrettyplayRuntime`, `get_runtime`, `__all__`); фасад-проверка:
  `python -c "from prettyplay import PrettyTest"`.
- `__init__.py` каждой клетки реэкспортирует публичные сущности клетки (по её CODEMANIFEST)
  из модулей, указанных в `location:` (относительные импорты + `__all__`) — примеры импортов
  в клеточных `.usages/` дают импорты из пакетов клеток, эта поверхность обязана работать:
  - `prettyplay/config/__init__.py`: `Config` (models), `load_config` (loader)
  - `prettyplay/reporting/__init__.py`: `StepHooks` (hooks), `StepReporter` (reporter)
  - `prettyplay/failures/__init__.py`: `PrettyplayError`, `ProductDefectError`,
    `IncurableStepError`, `LlmUnavailableError` (errors)
  - `prettyplay/driver/__init__.py`: `DriverSession` (session), `PageFacade`,
    `LocatorFacade` (page)
  - `prettyplay/cache/__init__.py`: `normalize_step_text` (text), `StepIdentity`,
    `CachedStep` (models), `StepCache` (store), `RunBudgets` (budgets)
  - `prettyplay/llm/__init__.py`: `LlmProvider`, `create_provider` (provider),
    `OpenAiProvider` (openai_provider), `AnthropicProvider` (anthropic_provider),
    `FailureClassification` (models)
  - `prettyplay/engine/__init__.py`: `run_step_code` (execution), `StepGenerator`
    (generator), `StepHealer` (healer)
- Фасад-проверка после каждой клетки: `python -c "from prettyplay.<клетка> import <сущность>"`
  (например `from prettyplay.cache import StepCache` — дословно из `storage.md`).
- Импорты внутри пакета — только относительные (`from ..cache.store import StepCache`);
  абсолютные — stdlib и third-party.
- Все модели — pydantic v2, `kw_only=True`, пустые дефолты, `None` только для явной
  отсутствующности (`screenshot`, `pyproject_path`, `cache_path`).
- Поверхность фасада драйвера — backward-compatibility контракт: расширять, никогда не
  переименовывать/удалять; при изменении поверхности синхронизировать `PAGE_API_SURFACE`
  в generator.py и `prettyplay/driver/.usages/facade.md`.
- Ключи LLM — только env (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`), никогда не из файлов и не в
  логах; клиент провайдера создавать лениво при первом запросе.
- Один запрос к провайдеру на попытку; повторы и бюджеты — исключительная прерогатива движка
  (`RunBudgets`), не провайдера.
- Никаких fixed delays в коде шагов и фасаде (auto-wait локаторов); библиотечный бэкофф
  `os.replace` на Windows — единственный разрешённый sleep (до 3×0.1 c).
- Логгер один: `logging.getLogger("prettyplay")`; события = имена хуков; контекст через
  `extra`; `on_cache_skipped` и сбой хука — WARNING, остальной жизненный цикл — INFO.
- ruff: line-length 120, complexity 10; зависимости в `pyproject.toml` с минимальными версиями
  (playwright, openai, anthropic, pydantic; `tomli>=2.0; python_version < "3.11"`; тестовые —
  в `[project.optional-dependencies].test`).
- Кэш-файл шага: заголовок `STEP_TEXT` / `CACHE_KEY` / `STEP_TYPE` / `CREATED_AT` (repr-литералы),
  затем код фиксированной формы `def step(page) -> None:`; файл без поля версии библиотеки.
- Сгенерированный код шага исполняется только через `run_step_code` (compile → namespace →
  step(page)); не регистрировать в `sys.modules`; не выполнять произвольные файлы.
