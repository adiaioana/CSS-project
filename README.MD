# Flux de alocare a proceselor și gestionare a memoriei

## 1. Stările unui proces

Un proces trece prin următoarele stări pe parcursul simulării:

```
NOT_ARRIVED ──► ON_DISK / (direct) ──► LOADING ──► READY ──► RUNNING
                    ▲                                  │         │
                    │                                  │         ▼
                 SAVING ◄── (evicție LRU) ─────────────┘    WAITING_SYS
                    │                                             │
                    └─────────────────────────────────────────── ┘
                                                                  ▼
                                                              FINISHED
```

| Stare | Semnificație |
|---|---|
| `NOT_ARRIVED` | Procesul nu a ajuns încă la `release_time` |
| `ON_DISK` | Procesul nu se află în RAM (fie nu a fost niciodată încărcat, fie a fost evacuat) |
| `LOADING` | Transfer disk → RAM în curs |
| `SAVING` | Transfer RAM → disk în curs (evicție LRU) |
| `READY` | Procesul este în RAM și așteptă un CPU liber |
| `RUNNING` | Procesul execută pe un CPU |
| `WAITING_SYS` | Procesul a emis un syscall și așteaptă procesul de sistem |
| `FINISHED` | Procesul și-a terminat toate burst-urile |

---

## 2. Evenimentul `PROCESS_RELEASE` — intrarea unui proces în sistem

La momentul `release_time` al unui proces, simulatorul generează un eveniment `PROCESS_RELEASE`. Handlerul apelează `_admit_process(pid)`.

### 2.1 `_admit_process(pid)` — logica de admitere în RAM

```
_admit_process(pid)
│
├─ [RAM disponibil pentru p.memory?]
│    DA → alocare directă în RAM
│         • p.in_memory = True
│         • ram_used += p.memory
│         • adaugă pid la capătul listei in_ram  (devine MRU)
│         • _enqueue_ready(p)  →  state = READY, adăugat în ready_queue
│         • _schedule()        →  încearcă să dispatch pe un CPU liber
│
└─ NU → apelează _lru_evict_for(pid)
         │
         ├─ [s-a putut evacua suficient?]
         │    DA (și există evacuați) →
         │         • state = ON_DISK
         │         • coadă disk: (pid, "load", transfer_time) după save-uri
         │         • disk se pompează automat după ce save-urile se termină
         │
         │    DA (fără evacuați, spațiu era deja disponibil) →
         │         • alocare directă (ca mai sus)
         │
         └─ NU (toți ocupanții RAM sunt RUNNING sau LOADING, nimic evacuabil) →
                  • state = ON_DISK
                  • pid adăugat în waiting_for_ram  (coadă de așteptare RAM)
                  • log: WAIT_FOR_RAM
```

---

## 3. `_lru_evict_for(pid)` — evacuarea LRU

Funcția caută în lista `in_ram` (ordonată LRU-oldest-first) primul proces evacuabil și îl scoate din RAM pentru a face loc procesului `pid`.

**Condiții de evacuabilitate** — un proces poate fi evacuat dacă și numai dacă starea sa este:
- `READY` — în coada de așteptare, nu execută
- `FINISHED` — terminat, RAM-ul său poate fi eliberat imediat

**Nu pot fi evacuate** procesele în stările: `RUNNING`, `WAITING_SYS`, `LOADING`, `SAVING`.

```
pentru fiecare candidat în in_ram (cel mai vechi primul):
    dacă candidat.state ∈ {READY, FINISHED}:
        • in_ram.remove(candidat)
        • ram_used -= candidat.memory
        • candidat.in_memory = False
        • candidat.state = SAVING
        • disk_queue.append((candidat, "save", transfer_time))
        • log: EVICT→DISK
        repetă până când ram_available(p.memory) == True

_pump_disk()  →  pornește primul transfer din coadă dacă discul e liber
```

---

## 4. Transferurile de disc — coada serială

Discul este o resursă **serial blocking**: un singur transfer poate fi activ la un moment dat.

```
disk_queue: deque de (pid, "save"/"load", duration)

_pump_disk():
    dacă disk_busy == False și disk_queue nu e goală:
        • scoate primul element
        • disk_busy = True
        • generează eveniment DISK_TRANSFER_END la time + duration
        • dacă "load": state = LOADING, log: LOAD←DISK_START
        • _gantt_start("DISK", pid, categorie)
```

### 4.1 La terminarea unui transfer (`DISK_TRANSFER_END`)

**Save (evacuare completă):**
```
• p.state = ON_DISK
• p.in_memory = False
• log: SAVED_TO_DISK
• dacă p nu e FINISHED → adăugat în waiting_for_ram
  (va fi reîncărcat când apare spațiu)
• _pump_disk()  →  continuă cu următorul transfer
• _try_admit_waiting()  →  încearcă să admită procese din lista de așteptare
```

**Load (încărcare completă):**
```
• p.in_memory = True
• ram_used += p.memory
• pid adăugat în in_ram  (devine MRU)
• log: LOADED_TO_RAM
• _enqueue_ready(p)  →  state = READY, intrare în ready_queue
• _schedule()  →  încearcă dispatch
```

---

## 5. `waiting_for_ram` — coada de așteptare RAM

Procesele ajung în `waiting_for_ram` în două situații:
1. **La `PROCESS_RELEASE`**: nu există niciun candidat evacuabil (toți sunt RUNNING/LOADING)
2. **După un save complet**: procesul evacuat este re-înregistrat automat pentru reîncărcare

### 5.1 `_try_admit_waiting()` — retry admitere

Apelată după orice eveniment care poate elibera RAM:
- `SLICE_EXPIRE` — un proces cedează CPU-ul și devine READY (evacuabil dacă e nevoie)
- `PROCESS_FINISH` — RAM-ul procesului terminat e eliberat imediat prin `_release_ram()`
- `SYS_PROC_END` — procesele cu syscall completat reintră în READY (evacuabile)
- `DISK_TRANSFER_END` — un save a terminat (spațiu potențial disponibil)

```
_try_admit_waiting():
    dacă waiting_for_ram e goală → return

    pid = waiting_for_ram[0]  (primul în coadă, FIFO)

    ├─ [RAM disponibil?]
    │    DA → admitere directă + _schedule()
    │
    ├─ [_lru_evict_for reușește?]
    │    DA → admitere directă + _schedule()
    │    DA (dar sunt save-uri în curs) →
    │         • scoate din waiting_for_ram
    │         • adaugă (pid, "load") în disk_queue
    │         (va fi încărcat după ce save-urile se termină)
    │
    └─ NU → rămâne în waiting_for_ram, retry la următorul eveniment
```

> **Notă de design**: se admite cel mult **un proces per apel** pentru a evita situația în care un proces tocmai admis este imediat evacuat pentru a face loc celui următor.

---

## 6. `_release_ram(pid)` — eliberare RAM la terminare

Când un proces ajunge la starea `FINISHED` (fie prin `_handle_process_finish`, fie prin `_handle_sys_proc_end`):

```
_release_ram(pid):
    dacă p.in_memory:
        • p.in_memory = False
        • ram_used -= p.memory
        • in_ram.remove(pid)
        • log: RAM_FREED
```

Imediat după, se apelează `_try_admit_waiting()` care poate admite primul proces din coada de așteptare fără nicio latență suplimentară.

---

## 7. Actualizarea ordinii LRU

Lista `in_ram` menține ordinea **LRU-oldest-first**: primul element este cel mai vechi (candidat la evacuare), ultimul este cel mai recent folosit (MRU).

Actualizarea are loc în `_enqueue_ready()`:
```python
if process.pid in self.in_ram:
    self.in_ram.remove(process.pid)   # scoate din poziția curentă
self.in_ram.append(process.pid)        # re-inserează la capăt (MRU)
process.last_used_time = self.time
```

Astfel, ori de câte ori un proces devine READY (după un burst, după un syscall, după o încărcare de pe disc), el este marcat ca **cel mai recent folosit** și devine ultimul candidat la evacuare.

---

## 8. Fluxul complet — exemplu vizual

```
t=0   P0 released (64MB) → RAM liberă (0/160) → admis direct → READY → dispatched
t=2   P1 released (64MB) → RAM liberă (64/160) → admis direct → READY → dispatched
t=8   P2 released (96MB) → RAM folosită (128/160), 32MB liber < 96MB necesar
        → _lru_evict_for: P0 și P1 sunt RUNNING → nimic evacuabil
        → waiting_for_ram.append(P2)

t=10  P0 termină burst → state=WAITING_SYS (syscall emis)
        → CPU0 liber → _try_admit_waiting():
             P0 e WAITING_SYS (nu evacuabil), P1 e RUNNING (nu evacuabil)
             → tot nu se poate
        Syscall procesat → P0 READY
        → P2 poate fi admis dacă P1 termină sau cedează

t=10  P1 termină burst (slice expire) → READY
        → _try_admit_waiting():
             P1 e acum READY (evacuabil!)
             → evacuează P1: ram_used 128→64, save queued
             → adaugă (P2, "load") în disk_queue după save
        → la t=11.28: P1 SAVED_TO_DISK → P2 LOAD←DISK_START
        → la t=13.20: P2 LOADED_TO_RAM → READY → dispatched
        → P1 adăugat în waiting_for_ram (va fi reîncărcat)
        → când P2 sau P0 termină → _release_ram → P1 readmis
```

---

## 9. Invariante menținute

| Invariant | Unde e garantat |
|---|---|
| `ram_used` ≤ `ram_size` în orice moment | `_admit_process` verifică înainte de alocare |
| Procesele RUNNING/WAITING_SYS nu sunt niciodată evacuate | Garda din `_lru_evict_for` |
| Discul procesează un singur transfer la un moment dat | Flag `disk_busy` în `_pump_disk` |
| Un proces evacuat cu muncă rămasă reintră în `waiting_for_ram` | `_handle_disk_transfer_end` (save branch) |
| RAM-ul e eliberat imediat la terminarea unui proces | `_release_ram` apelat la `STATE_FINISHED` |
| Admiterea în RAM se face cel mult 1 proces per trigger | `_try_admit_waiting` fără buclă externă |