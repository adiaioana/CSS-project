# Flow description

Input total
- schelduling time slice de la Round Robin
- nr de procesoare
- Memoria RAM/virtuala pe care se pun procesele pre executare
- Cost de timp pentru mutarea unui proces de pe disk pe RAM 
- Lista proceselor
  - Release time (cand vine in schema)
  - Required memory
  - Lista de taskuri (doar timpii lor): unu system, unu user


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