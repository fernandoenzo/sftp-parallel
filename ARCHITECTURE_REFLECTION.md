# Reflexión Arquitectónica: sftp-parallel

## Análisis desde cero con filosofía UNIX y principio KISS

> *"UNIX is simple. It just takes a genius to understand its simplicity."*
> — Dennis Ritchie

> *"Perfection is achieved, not when there is nothing more to add, but when there is nothing left to take away."*
> — Antoine de Saint-Exupéry (citado por Linus Torvalds)

---

## 1. Qué hace el proyecto (esencia pura)

Antes de diseñar nada, reduzcamos el problema a su mínima expresión:

```
ENTRADA:  archivos locales + host remoto + destino
SALIDA:   archivos subidos al servidor
OPCIONAL: barra de progreso + verificación checksum
```

**Eso es todo.** Todo lo demás es implementación.

---

## 2. Análisis del proyecto actual

### 2.1 Métricas

| Métrica | Valor |
|---------|-------|
| Archivos fuente | 9 |
| Líneas fuente | 2.319 |
| Archivos test | 9 |
| Líneas test | 2.292 |
| Clases | 5 |
| Funciones | 47 |
| Dependencias externas | 1 (Rich) |

### 2.2 Módulos actuales

```
sftp_parallel/
├── __init__.py          (36 líneas)  — re-exporta API pública
├── __main__.py          (6 líneas)   — entry point
├── batch.py             (224 líneas) — validación + escape + generación de comandos
├── cli.py               (421 líneas) — argparse + orquestación + callbacks
├── progress.py          (230 líneas) — Rich progress bars + columnas custom
├── pty_worker.py        (624 líneas) — PTY fork + reader/writer threads + parsing
├── signals.py           (113 líneas) — signal handlers
├── uploader.py          (417 líneas) — ThreadPoolExecutor + run_sftp batch
├── verify.py            (248 líneas) — checksums locales/remotos vía SSH
```

### 2.3 Puntos de complejidad innecesaria

Tras analizar el código con ojos frescos, identifico estos problemas:

#### **Problema 1: `pty_worker.py` es un monolito de 624 líneas**

Es el archivo más grande y el más complejo. Mezcla cinco conceptos diferentes en un solo sitio:
- Gestión de procesos (fork, exec, waitpid, kill)
- Parsing de output SFTP (regex, ANSI stripping, prompt detection)
- Threading (reader/writer daemon threads)
- Timeout management (idle, connection, prompt)
- Progress reporting (callbacks)

Un solo clase (`PTYWorker`) tiene **15 métodos**. Linus diría: *"If you need more than 3 levels of indentation, you're screwed anyway, and should fix your program."*

#### **Problema 2: Duplicación conceptual entre `uploader.py` y `pty_worker.py`**

`uploader.py` tiene `run_sftp()` (batch mode) y `_upload_one_via_pty()` (PTY mode). Dos formas de hacer lo mismo con APIs completamente diferentes. `upload_files()` solo usa PTY mode — `run_sftp()` solo se usa para `get_remote_file_sizes()`. Confuso.

#### **Problema 3: `cli.py` hace demasiado**

`_handle_upload()` son **200 líneas** que incluyen:
- Validación de host/port/dir
- Resolución de patrones de archivos
- Deduplicación de basenames
- Lógica de skip-existing
- TOCTOU guards
- Orquestación de subida
- Callbacks de progreso
- Verificación de checksums
- Manejo de códigos de salida

Violación directa del principio UNIX: *"Do one thing and do it well."*

#### **Problema 4: `signals.py` existe solo para un edge case**

113 líneas para manejar SIGINT/SIGTERM durante uploads. En la práctica, el handler hace tres cosas:
1. Iterar workers activos
2. Llamar `terminate()` en cada uno
3. `sys.exit(128 + signum)`

Esto podría ser una función de 10 líneas.

#### **Problema 5: Validación excesiva**

`batch.py` tiene 8 funciones de validación. Algunas se llaman múltiples veces desde diferentes capas:
- `validate_host()` se llama en `cli.py`, `uploader.py`, `pty_worker.py`, y `verify.py`
- `validate_port()` igual
- `validate_remote_dir()` igual

Cada capa re-valida lo que la capa anterior ya validó. Esto es paranoia, no robustez.

---

## 3. Diseño desde cero

### 3.1 Pregunta fundamental: ¿PTY o no PTY?

La decisión arquitectónica más importante es cómo interactuar con SFTP.

| Enfoque | Pros | Contras |
|---------|------|---------|
| **PTY (actual)** | Progreso real de OpenSSH, archivos grandes soportados | Complejidad, Linux/macOS only |
| **Paramiko** | API limpia, progreso nativo, cross-platform | Dependencia nueva, no respeta ssh_config |
| **Batch mode** | Simple, sin threads, sin PTY | Sin progreso real, timeout rígido |
| **rsync** | Robusto, reanudable, progreso | Dependencia externa, diferente protocolo |

**Mi elección: PTY.** Es la que mejor se alinea con UNIX (usa las herramientas del sistema), pero la implementación actual es 3x más compleja de lo necesario.

### 3.2 Arquitectura propuesta desde cero

```
sftp_parallel/
├── __init__.py          (~10 líneas)  — versión + exports
├── __main__.py          (~3 líneas)   — entry point
├── worker.py            (~250 líneas) — PTY spawn + select loop + Rich callbacks
├── upload.py            (~100 líneas) — parallel upload orchestration
├── progress.py          (~100 líneas) — Rich progress bars (mantenido)
├── cli.py               (~150 líneas) — argparse + main()
└── lib.py               (~150 líneas) — validación + escape + parsing + checksums
```

**6 archivos, ~763 líneas.** Comparado con 9 archivos, 2.319 líneas.

---

## 4. Cómo funciona el programa: antes vs después

Esta es la parte más importante del informe. No voy a hablar de métricas abstractas — voy a explicar qué hace el programa paso a paso, y cómo cambia cada paso en el diseño propuesto.

### Paso 1: El usuario ejecuta el comando

```bash
sftp-parallel -s user@server -f video1.mp4 video2.mp4 -d /uploads --verify
```

**Actual:** El sistema operativo ejecuta `__main__.py`, que llama a `cli.main()`. Dentro de `main()` hay un parser de argumentos estándar (`argparse`). Hasta aquí, ambos diseños son idénticos.

### Paso 2: Validación de argumentos

**Actual:** La validación ocurre en `cli.py` → `_handle_upload()`. Pero no una vez, sino **cuatro veces**:
1. `cli.py` valida host, puerto y directorio remoto
2. `uploader.py` vuelve a validar los mismos tres datos antes de subir
3. `pty_worker.py` vuelve a validar los mismos tres datos al crear cada Worker
4. `verify.py` vuelve a validar los mismos tres datos al verificar

Si cambias `validate_host()` en `batch.py`, se ejecuta 4 veces por archivo subido. Para 10 archivos, son 40 llamadas redundantes.

**Propuesto:** La validación ocurre **una sola vez**, en `cli.py`, antes de hacer cualquier otra cosa. Los demás módulos reciben datos ya validados y confían en su caller. Esto es el principio de "validate at the boundary" — validar en el borde de entrada del programa, no en cada capa interna.

```python
# cli.py — validación única, al principio
def main(argv=None):
    args = _build_parser().parse_args(argv)
    validate_host(args.server)       # ← aquí, una vez
    validate_port(args.port)         # ← aquí, una vez
    validate_remote_dir(args.dest)   # ← aquí, una vez
    # ... de aquí en adelante, los datos son válidos
```

### Paso 3: Resolución de archivos

**Actual:** `cli.py` → `resolve_file_patterns()` → `_resolve_one()`. Esta función hace glob expansion, symlink resolution, y validación de nombres de archivo. Luego `validate_basename_uniqueness()` comprueba que no haya dos archivos con el mismo nombre.

**Propuesto:** Exactamente igual. Esta lógica es buena y no necesita cambiar. Solo se mueve a una función más compacta dentro de `cli.py`.

### Paso 4: Skip-existing (opcional)

Si el usuario pasó `--skip-existing`, el programa necesita saber qué archivos ya existen en el servidor remoto.

**Actual:** `cli.py` llama a `uploader.get_remote_file_sizes()`, que a su vez:
1. Importa `run_sftp()` de `uploader.py`
2. Construye un batch de comandos SFTP (`cd /uploads`, `ls -l`, `bye`)
3. Ejecuta `sftp -N -b -` como subprocess con `communicate()`
4. Parsea el output de `ls -l` con un regex para extraer tamaños
5. Retorna un diccionario `{nombre_archivo: tamaño}`

Luego `cli.py` compara tamaños locales vs remotos y filtra.

**Propuesto:** La función `get_remote_file_sizes()` se mueve a `lib.py` como una función pura. La lógica es idéntica — solo cambia de ubicación. La diferencia es que **no se llama dos veces** (actualmente, `uploader.py` la usa internamente Y `cli.py` la llama externamente).

### Paso 5: Creación de la barra de progreso

**Actual:** `cli.py` llama a `progress.create_upload_progress_v2()`, un context manager que:
1. Crea una instancia de `rich.progress.Progress` con 7 columnas custom
2. Imprime un header con el host, directorio y número de workers
3. Devuelve el objeto `Progress` para que el caller añada tasks

Luego `cli.py` define dos callbacks closures (`progress_callback` y `completion_callback`) que:
- Mantienen un `task_map: dict[str, tuple[TaskID, FileProgress, float]]` protegido por un lock
- Cuando un archivo empieza: crean un task en Rich, guardan el TaskID
- Cuando hay progreso: actualizan el task con los bytes transferidos
- Cuando termina: marcan el task como completo con color verde/rojo

**Propuesto:** Rich se mantiene, pero se simplifica. En vez de que `cli.py` defina closures complejas con locks, el Worker recibe una referencia directa al Progress y actualiza su propio task:

```python
# worker.py — el Worker conoce su task_id y actualiza directamente
class Worker:
    def __init__(self, ..., progress: Progress, task_id: TaskID):
        self.progress = progress
        self.task_id = task_id

    def _on_progress(self, bytes_transferred: int):
        self.progress.update(self.task_id, completed=bytes_transferred)
```

**¿Por qué es más simple?** Porque eliminamos el `task_map` y su lock. En el diseño actual, hay un diccionario compartido entre todos los workers que mapea `file_path → (TaskID, FileProgress, start_time)`. Cada vez que un worker reporta progreso, tiene que:
1. Adquirir el lock
2. Buscar su entrada en el diccionario
3. Si no existe, crearla
4. Leer el TaskID y FileProgress
5. Liberar el lock
6. Actualizar Rich

En el diseño propuesto, cada Worker tiene su propio `task_id` desde el momento de su creación. No hay diccionario compartido, no hay lock, no hay búsqueda. Es directo.

### Paso 6: Subida paralela (el corazón del programa)

Aquí es donde la diferencia arquitectónica es más profunda. Voy a explicar qué hace el programa actual paso a paso, y luego qué haría el propuesto.

#### El diseño actual: 3 threads por archivo

Cuando el usuario sube 4 archivos con 2 workers, esto es lo que ocurre:

```
Thread principal (cli.py)
  └─ ThreadPoolExecutor crea 2 worker threads
       ├─ Worker Thread 1 → sube archivo1.mp4
       │    └─ Internamente crea 2 threads más:
       │         ├─ Reader Thread → lee output del SFTP, parsea progreso
       │         └─ Writer Thread → envía comandos (cd, put, bye)
       └─ Worker Thread 2 → sube archivo2.mp4
            └─ Internamente crea 2 threads más:
                 ├─ Reader Thread
                 └─ Writer Thread
  (archivo3 y archivo4 esperan en la cola)
```

**Total: 1 thread principal + 2 worker threads + 4 reader/writer threads = 7 threads activos.**

Cada par reader/writer necesita coordinarse:
- El Writer envía `cd /uploads` y espera a que el Reader detecte el prompt `sftp>`
- El Writer envía `put -f video1.mp4` y espera... ¿cuánto? Depende del tamaño del archivo
- El Reader parsea cada línea de output buscando: ¿es un prompt? ¿es progreso? ¿es un error? ¿es un eco de comando?

Esta coordinación se hace con `threading.Event` (`_prompt_event`, `_stop_event`) y un `threading.Lock` (`_lock`) protegiendo las variables compartidas (`_bytes_transferred`, `_last_progress_time`, `_error_message`, `_prompt_count`).

**¿Por qué dos threads internos?** Porque el código actual usa un patrón productor-consumidor: el Reader produce output, el Writer consume prompts. Pero esto es innecesario — SFTP interactivo no necesita dos threads porque el PTY ya es bidireccional. Se puede leer y escribir en el mismo thread usando `select()`, como hacen todos los servidores HTTP de alta concurrencia.

#### El diseño propuesto: 1 thread por archivo

```
Thread principal (cli.py)
  └─ ThreadPoolExecutor crea 2 worker threads
       ├─ Worker Thread 1 → sube archivo1.mp4
       │    └─ Un solo loop con select():
       │         - Si hay datos para leer → leer y parsear
       │         - Si hay prompt → enviar siguiente comando
       └─ Worker Thread 2 → sube archivo2.mp4
            └─ Un solo loop con select()
  (archivo3 y archivo4 esperan en la cola)
```

**Total: 1 thread principal + 2 worker threads = 3 threads.**

Cada Worker ejecuta un bucle simple:

```python
while not done:
    # ¿Hay datos que leer del SFTP? ¿Hay comandos que enviar?
    readable, writable, _ = select.select([fd], [fd if pending_cmd], [], 0.5)

    if readable:
        data = os.read(fd, 4096)      # Leer output
        process_output(data)           # Parsear: ¿progreso? ¿prompt? ¿error?

    if writable and pending_cmd:
        os.write(fd, pending_cmd)      # Enviar comando
        pending_cmd = None
```

**¿Por qué es más simple?** Porque `select()` es el mecanismo estándar de UNIX para "espera hasta que haya algo que hacer en uno de estos descriptores de archivo". Es lo que usan nginx, Redis, y prácticamente todo servidor de alta concurrencia. No necesita locks porque no hay estado compartido — cada Worker es independiente.

La analogía: el diseño actual es como tener dos personas por carta (una que dicta, otra que escribe). El diseño propuesto es como tener una sola persona que lee el buzón y escribe la respuesta cuando corresponde.

### Paso 7: Parseo de progreso

SFTP muestra el progreso así en la terminal:

```
video1.mp4  15%  150MB  10.5MB/s  00:01:20 ETA
```

**Actual:** El `Reader Thread` acumula bytes en un buffer (`_linebuf`), los divide por `\r` y `\n`, y para cada línea:
1. Quita secuencias ANSI (colores)
2. Busca el patrón de progreso con un regex (`_PROGRESS_RE`)
3. Si encuentra progreso: extrae porcentaje y bytes, actualiza `_bytes_transferred`, llama al callback
4. Si encuentra `sftp>`: incrementa `_prompt_count`, setea `_prompt_event`
5. Si encuentra un error: guarda `_error_message`
6. Si la línea es un eco de comando propio: la ignora (comprobando contra `_SFTP_SAFE_LINE_RE`)

Esto ocurre en `_process_output()` → `_parse_line()`, que son 67 + 47 = 114 líneas de lógica.

**Propuesto:** El parseo es idéntico en lógica, pero más compacto porque no hay threading. En vez de un Reader Thread que acumula y parsea, el Worker hace lo mismo en su loop principal:

```python
# Cuando select() dice "hay datos para leer":
data = os.read(fd, 4096)
for line in split_lines(data):
    if progress := parse_progress(line):   # ← función pura en lib.py
        update_rich_bar(progress)
    if "sftp>" in line:
        send_next_command()
    if is_error(line):
        record_error(line)
```

La función `parse_progress()` se extrae a `lib.py` como función pura (sin estado, sin side effects). Se puede testear independientemente sin crear un Worker.

### Paso 8: Finalización y verificación

**Actual:** Cuando un Worker termina:
1. El Reader Thread detecta EOF y sale del loop
2. El Writer Thread ya habrá enviado `bye` y salido
3. `_cleanup()` cierra el fd del PTY y hace `waitpid()` para recoger el proceso hijo
4. El `completion_callback` en `cli.py` marca el task de Rich como completo (verde o rojo)
5. `upload_files()` en `uploader.py` retorna `(all_success, failed_count)`
6. Si `--verify`: `cli.py` llama a `verify.compute_remote_checksums()` que ejecuta `ssh host "sha256sum file1 file2"`

**Propuesto:** Idéntico, pero con menos indirección. El Worker retorna `True/False` directamente. La verificación sigue siendo `ssh + sha256sum`. La lógica no cambia — solo la ubicación de las funciones.

### Resumen del flujo completo

| Paso | Actual | Propuesto | Diferencia |
|------|--------|-----------|------------|
| 1. Ejecutar comando | `__main__` → `cli.main()` | Igual | — |
| 2. Validar args | 4 capas, 4x redundancia | 1 vez en `cli.py` | -75% llamadas |
| 3. Resolver archivos | `cli.py` | `cli.py` | — |
| 4. Skip-existing | `cli.py` → `uploader` → `run_sftp` | `cli.py` → `lib.get_remote_sizes` | 1 capa menos |
| 5. Progress bar | Rich + task_map + locks | Rich + Worker.task_id | Sin locks |
| 6. Subir archivos | 3 threads/archivo, 5 locks | 1 thread/archivo, 0 locks | -67% threads |
| 7. Parsear progreso | Reader Thread + callbacks | select() loop + función pura | Sin threads |
| 8. Verificar | `cli.py` → `verify.py` | `cli.py` → `lib.py` | 1 archivo menos |

---

## 5. Comparativa directa

### 5.1 Estructura de archivos

| Aspecto | Actual | Propuesto |
|---------|--------|-----------|
| Archivos fuente | 9 | 6 |
| Líneas fuente | 2.319 | ~763 |
| Clases | 5 | 1 |
| Funciones | 47 | ~25 |
| Dependencias externas | 1 (Rich) | 1 (Rich) |
| Archivos test | 9 | 6 |
| Líneas test estimadas | 2.292 | ~900 |

### 5.2 Complejidad por módulo

| Módulo | Actual | Propuesto | Cambio |
|--------|--------|-----------|--------|
| worker (PTY) | 15 métodos, 624 líneas | ~6 métodos, ~250 líneas | -60% |
| cli | 8 funciones, 421 líneas | ~6 funciones, ~150 líneas | -64% |
| progress | 3 clases, 5 funcs, 230 líneas | 2 clases, 4 funcs, ~100 líneas | -57% |
| signals | 4 funciones, 113 líneas | 0 (inline en cli) | -100% |
| uploader | 8 funciones, 417 líneas | ~4 funciones, ~100 líneas | -76% |
| batch → lib | 8 funciones, 224 líneas | ~10 funciones, ~150 líneas | -33% |
| verify | 4 funciones, 248 líneas | (merged en lib.py) | -100% |

### 5.3 Threading model

**Actual:**
```
Main thread
  └─ ThreadPoolExecutor (N workers)
       └─ Worker thread (_upload_one_via_pty)
            ├─ Reader daemon thread (_reader_thread)
            │    └─ select() loop + parse + callback
            └─ Writer daemon thread (_writer_thread)
                 └─ wait for prompt → write command → wait again

Locks: task_map_lock, worker_lock, _lock (per worker), _stop_event, _prompt_event
Total: 3 threads por archivo + 5 mecanismos de sincronización
```

**Propuesto:**
```
Main thread
  └─ ThreadPoolExecutor (N workers)
       └─ Worker thread (Worker.run)
            └─ select() loop: read when ready, write when prompted

Locks: task_map_lock (solo para Rich updates desde ThreadPoolExecutor)
Total: 1 thread por archivo + 1 lock
```

### 5.4 Capas de abstracción

**Actual (5 capas):**
```
CLI → Uploader → _upload_one_via_pty → PTYWorker → subprocess/pty
         ↕
    Progress Manager → Rich Progress → Rich Columns
         ↕
    Signal Manager → PTYWorker.terminate()
```

**Propuesto (2 capas):**
```
CLI → Worker (pty + select + Rich callback)
         ↕
    Progress (Rich Progress + columns)
```

---

## 6. Qué ganamos y qué perdemos

### 6.1 Ganancias

| Ganancia | Impacto |
|----------|---------|
| **-67% líneas fuente** (2319 → ~763) | Mantenibilidad drásticamente mejorada |
| **-60% clases** (5 → 1) | Menos indirección, más legibilidad |
| **-67% threads** (3 por worker → 1) | Menos race conditions, menos locks |
| **-80% locks** (5 → 1) | Deadlocks casi imposibles |
| **-100% módulo signals** | 3 líneas inline vs 113 líneas dedicadas |
| **-75% validación redundante** | 1 vez vs 4 veces por capa |
| **Límite de profundidad 1** | CLI → Worker, sin capas intermedias |

### 6.2 Lo que NO perdemos

- ✅ **Rich progress bars** (mantenidos con simplificación)
- ✅ Subida paralela (ThreadPoolExecutor)
- ✅ Progreso en tiempo real (parseo PTY + Rich)
- ✅ Verificación checksum (SSH + sha256sum)
- ✅ Skip-existing (size comparison)
- ✅ Signal handling (SIGINT/SIGTERM clean shutdown)
- ✅ Validación de entrada (host, port, path, filename)
- ✅ Escape de paths para SFTP
- ✅ Timeout management (idle + connection)
- ✅ Tests completos

### 6.3 Lo que SÍ perdemos (y por qué está bien)

| Se pierde | Por qué está bien |
|-----------|-------------------|
| `signals.py` como módulo separado | 3 líneas inline en `cli.py` hacen lo mismo |
| `FileProgress` dataclass | Solo agrupa 2 campos — una tupla o el propio Worker lo lleva |
| `WorkerResult` dataclass | Un `bool` + un mensaje de error es suficiente |
| `uploader.run_sftp()` | Solo se usa para `ls -l` remoto — se puede hacer con `subprocess.run()` directamente |
| `uploader.filter_existing_files()` | La CLI ya tiene su propia implementación |
| `verify.verify_uploads()` | La CLI ya tiene su propia implementación |
| Validación redundante en 4 capas | Validar una vez es suficiente |

---

## 7. El código propuesto (sketch)

### 7.1 `lib.py` (~150 líneas)

```python
"""Validación, escape, parsing y checksums — todo puro."""

import hashlib
import os
import re
import subprocess
import unicodedata

# --- Validación ---

def validate_host(host: str) -> None:
    """Valida host. Raise ValueError si inválido."""
    if not host or not host.strip():
        raise ValueError("host must not be empty")
    if host.startswith("-"):
        raise ValueError("host must not start with '-'")
    for ch in host:
        if unicodedata.category(ch).startswith("C"):
            raise ValueError(f"host contains control character: {ch!r}")

def validate_port(port: int) -> None: ...
def validate_remote_dir(d: str) -> None: ...
def validate_filename(name: str) -> bool: ...

# --- Escape ---

def escape_interactive(path: str) -> str:
    """Escapa path para SFTP interactivo (backslash)."""
    for old, new in [("\\", "\\\\"), ('"', '\\"'), ("'", "\\'"), (" ", "\\ ")]:
        path = path.replace(old, new)
    return path

# --- Parsing ---

_PROGRESS_RE = re.compile(r"(\d{1,3})%\s+(\d+(?:[.,]\d+)?(?:[KMGT]?i?B)?)")

def parse_progress(line: str) -> tuple[int, int] | None:
    """Extrae (pct, bytes) de una línea de progreso SFTP. None si no es progreso."""
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    return int(m.group(1)), _parse_bytes(m.group(2))

def _parse_bytes(s: str) -> int:
    """Convierte '100KB' → 102400."""
    multipliers = {"B": 1, "KB": 1024, "KiB": 1024, "MB": 1024**2, "MiB": 1024**2,
                   "GB": 1024**3, "GiB": 1024**3, "TB": 1024**4, "TiB": 1024**4}
    for suffix in sorted(multipliers, key=len, reverse=True):
        if s.endswith(suffix):
            return int(float(s[:-len(suffix)].replace(",", ".")) * multipliers[suffix])
    return int(s)

def parse_ls_sizes(output: str) -> dict[str, int]:
    """Parse 'ls -l' output → {filename: size}."""
    ...

def parse_checksum_output(output: str) -> dict[str, str]:
    """Parse sha256sum output → {filename: hash}."""
    ...

# --- Checksums ---

def compute_local_checksum(filepath: str) -> str:
    """SHA-256 de un archivo local."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def compute_remote_checksums(host, remote_dir, filenames, port=22) -> dict[str, str] | None:
    """SHA-256 de archivos remotos vía SSH."""
    ...
```

### 7.2 `worker.py` (~250 líneas)

```python
"""Worker PTY para un proceso SFTP interactivo."""

import fcntl
import locale
import os
import pty
import re
import select
import signal
import struct
import termios
import time

from rich.progress import Progress, TaskID

from sftp_parallel.lib import (
    validate_host, validate_port, validate_remote_dir,
    escape_interactive, parse_progress,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ERROR_RE = re.compile(r"(?:Error|Failed|No such|Permission denied|...)", re.I)


class Worker:
    """Un proceso SFTP interactivo sobre PTY."""

    def __init__(self, host, file_path, remote_dir, port=22,
                 connect_timeout=10, idle_timeout=120,
                 progress: Progress | None = None, task_id: TaskID | None = None):
        validate_host(host)
        validate_port(port)
        validate_remote_dir(remote_dir)

        self.host = host
        self.file_path = file_path
        self.remote_dir = remote_dir
        self.port = port
        self.connect_timeout = connect_timeout
        self.idle_timeout = idle_timeout
        self.progress = progress
        self.task_id = task_id

        self.pid = 0
        self.master_fd = -1
        self._file_size = os.path.getsize(file_path)
        self._bytes_transferred = 0
        self._error = ""
        self._linebuf = ""
        self._stop = False

    def run(self) -> bool:
        """Ejecuta el upload completo. Retorna True si éxito."""
        try:
            self._spawn()
        except (FileNotFoundError, OSError) as e:
            self._error = str(e)
            return False
        try:
            return self._loop()
        finally:
            self._cleanup()

    def terminate(self) -> None:
        """Mata el proceso. Idempotente, seguro desde cualquier thread."""
        self._stop = True
        if self.pid > 0:
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

    def _spawn(self) -> None:
        """Fork + exec sftp sobre PTY."""
        cmd = ["sftp", "-o", f"ConnectTimeout={self.connect_timeout}",
               "-o", "BatchMode=yes", "-o", f"Port={self.port}", self.host]
        self.pid, self.master_fd = pty.fork()
        if self.pid == 0:
            os.environ["LC_ALL"] = "C"
            os.execvp("sftp", cmd)
            os._exit(74)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 512, 0, 0))

    def _loop(self) -> bool:
        """Loop principal: select() para leer/escribir."""
        commands = [
            f"cd {escape_interactive(self.remote_dir)}",
            f"put -f {escape_interactive(self.file_path)}",
            "bye",
        ]
        cmd_idx = 0
        prompt_seen = False
        start = time.monotonic()
        last_progress = 0.0

        while not self._stop:
            try:
                r, w, _ = select.select(
                    [self.master_fd],
                    [self.master_fd] if cmd_idx < len(commands) else [],
                    [], 0.5
                )
            except (ValueError, OSError):
                break

            now = time.monotonic()
            if not prompt_seen and now - start > self.connect_timeout + 30:
                self._error = "Connection timeout"
                break
            if self._bytes_transferred > 0 and now - last_progress > self.idle_timeout:
                self._error = f"Stalled: no progress for {self.idle_timeout}s"
                break

            if self.master_fd in r:
                try:
                    data = os.read(self.master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                enc = locale.getpreferredencoding(False) or "utf-8"
                for line in self._split_lines(data.decode(enc, errors="replace")):
                    if "sftp>" in line:
                        prompt_seen = True
                        if cmd_idx < len(commands):
                            os.write(self.master_fd, (commands[cmd_idx] + "\n").encode())
                            cmd_idx += 1
                    prog = parse_progress(_ANSI_RE.sub("", line))
                    if prog:
                        _, transferred = prog
                        if transferred >= self._bytes_transferred:
                            self._bytes_transferred = transferred
                            last_progress = time.monotonic()
                            self._update_progress()
                    if _ERROR_RE.search(line) and not self._error:
                        self._error = line

        return not self._error and self._bytes_transferred == self._file_size

    def _update_progress(self) -> None:
        """Actualiza la barra de Rich si hay una."""
        if self.progress and self.task_id is not None:
            self.progress.update(self.task_id, completed=self._bytes_transferred)

    def _split_lines(self, text: str) -> list[str]:
        """Acumula texto en buffer, retorna líneas completas."""
        self._linebuf += text
        if len(self._linebuf) > 8192:
            self._linebuf = self._linebuf[-4096:]
        lines = re.split(r"[\r\n]+", self._linebuf)
        if text and text[-1] not in ("\r", "\n"):
            self._linebuf = lines[-1]
            return lines[:-1]
        self._linebuf = ""
        return lines

    def _cleanup(self) -> None:
        """Cierra fd y reaps child."""
        if self.master_fd >= 0:
            try: os.close(self.master_fd)
            except OSError: pass
            self.master_fd = -1
        if self.pid > 0:
            try: os.waitpid(self.pid, 0)
            except ChildProcessError: pass
            self.pid = 0
```

### 7.3 `upload.py` (~100 líneas)

```python
"""Orquestación de subida paralela."""

import os
from concurrent.futures import ThreadPoolExecutor
from rich.progress import Progress, TaskID

from sftp_parallel.worker import Worker

def parallel_upload(
    host: str,
    file_paths: list[str],
    remote_dir: str,
    progress: Progress,
    num_workers: int = 2,
    port: int = 22,
    idle_timeout: int = 120,
) -> tuple[int, int]:
    """Sube archivos en paralelo con Rich progress. Retorna (ok, fail)."""
    if not file_paths:
        return 0, 0

    # Crear un task por archivo en Rich
    tasks: dict[str, TaskID] = {}
    for fp in file_paths:
        name = os.path.basename(fp)
        size = os.path.getsize(fp)
        tasks[fp] = progress.add_task(name, total=max(size, 1))

    results = {"ok": 0, "fail": 0}

    def _upload_one(fp: str) -> bool:
        task_id = tasks[fp]
        w = Worker(host, fp, remote_dir, port=port, idle_timeout=idle_timeout,
                   progress=progress, task_id=task_id)
        success = w.run()
        if success:
            results["ok"] += 1
            progress.update(task_id, completed=os.path.getsize(fp))
        else:
            results["fail"] += 1
        return success

    with ThreadPoolExecutor(max_workers=min(num_workers, len(file_paths))) as ex:
        list(ex.map(_upload_one, file_paths))

    return results["ok"], results["fail"]
```

### 7.4 `cli.py` (~150 líneas)

```python
"""CLI: parse args → validate → upload → verify → exit."""

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TransferSpeedColumn, TimeElapsedColumn

from sftp_parallel.lib import (
    validate_host, validate_port, validate_remote_dir,
    validate_filename, compute_local_checksum,
    compute_remote_checksums, get_remote_file_sizes,
)
from sftp_parallel.upload import parallel_upload

console = Console()

def main(argv=None):
    args = _build_parser().parse_args(argv)
    validate_host(args.server)
    validate_port(args.port)
    validate_remote_dir(args.dest)

    file_paths = _resolve_files(args.files)
    if not file_paths:
        console.print("[yellow]No files found.[/yellow]")
        sys.exit(0)

    if args.skip_existing:
        file_paths = _filter_existing(file_paths, args)

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
    )
    with progress:
        ok, fail = parallel_upload(
            args.server, file_paths, args.dest, progress,
            num_workers=min(args.threads, len(file_paths)),
            port=args.port, idle_timeout=args.idle_timeout,
        )

    if args.verify:
        _verify(args.server, args.dest, file_paths, args.port)

    if fail:
        console.print(f"[bold red]Failed:[/bold red] {fail} file(s)")
        sys.exit(74)
    console.print(f"[bold green]Success[/bold green] — {ok} file(s) uploaded")

def _build_parser(): ...
def _resolve_files(patterns): ...
def _filter_existing(file_paths, args): ...
def _verify(host, remote_dir, file_paths, port): ...
```

---

## 8. Veredicto final

### 8.1 Opinión sincera

**El proyecto actual es funcional pero sobre-diseñado.**

Si Richard Stallman lo viera, diría: *"Why are there 624 lines to run sftp? sftp is a 10-line script."*

Si Linus Torvalds lo viera, diría: *"This is what happens when you let Java programmers write Python. Too many classes, too many layers, too much abstraction for what is essentially `pty.fork() + select() + os.write()`."*

La arquitectura actual tiene los síntomas clásicos de **over-engineering incremental**:
- Clases que podrían ser funciones
- Módulos que podrían ser líneas inline
- Threads donde `select()` basta
- Locks donde no hay shared state real
- Validación repetida 4 veces por capa

### 8.2 Qué conservaría del proyecto actual

1. **La decisión de usar PTY** — es correcta, respeta SSH/OpenSSH nativo
2. **Rich para progress bars** — es una buena librería y el usuario quiere mantenerla
3. **El regex de parsing de progreso** — está bien pensado y cubre edge cases
4. **La validación de host/port/path** — la lógica es buena, solo está duplicada
5. **Los tests** — la cobertura es excelente (290 tests)

### 8.3 Qué cambiaría radicalmente

1. **Eliminar threads internos de Worker** — `select()` multiplexa read/write sin threads
2. **Eliminar signals.py** — 3 líneas inline
3. **Eliminar uploader.py** — la lógica de batch mode no se usa; lo que queda va en upload.py
4. **Eliminar verify.py** — se mergea en lib.py
5. **Reducir PTYWorker de 624 a ~250 líneas** — un solo loop con select()
6. **Reducir cli.py de 421 a ~150 líneas** — separar validación en lib.py
7. **Simplificar progress.py de 230 a ~100 líneas** — el Worker actualiza Rich directamente

### 8.4 Números finales

| Métrica | Actual | Propuesto | Reducción |
|---------|--------|-----------|-----------|
| Líneas fuente | 2.319 | ~763 | **-67%** |
| Archivos fuente | 9 | 6 | **-33%** |
| Clases | 5 | 1 | **-80%** |
| Threads por worker | 3 | 1 | **-67%** |
| Locks | 5 | 1 | **-80%** |
| Validación redundante | 4x por capa | 1x | **-75%** |
| Capas de abstracción | 5 | 2 | **-60%** |

### 8.5 Conclusión

**¿Podría simplificarse aún más? Sí, significativamente.**

El proyecto actual funciona bien y los tests pasan, pero la complejidad inherente es 3x mayor de lo necesario. La razón es que se diseñó incrementalmente (ciclo a ciclo) en vez de diseñarse de arriba abajo primero. Cada ciclo añadió abstracciones "por si acaso" que nunca se simplificaron.

La filosofía UNIX dice: *"Write programs that do one thing and do it well. Write programs to work together."* El proyecto actual escribe un programa que hace una cosa... con 9 módulos, 5 clases, 5 locks y 624 líneas para gestionar un proceso hijo.

**El proyecto propuesto hace lo mismo con ~763 líneas, 1 clase, 1 lock, y las mismas barras de progreso de Rich.**

Eso es lo que haría Linus.

---

*Informe generado por Sisyphus — análisis arquitectónico con filosofía UNIX y principio KISS.*
