# Overview
This document summarizes COBOL artifacts extracted from the workspace, including programs and copybooks. A total of 10 COBOL artifacts were found.

## COUSR00C
This artifact is a COBOL program (`cam.cobol.program`) with source file `app/cbl/COUSR00C.cbl`.
It includes Identification, Environment, Data, and Procedure divisions.

### Paragraphs
- **MAIN-PARA** performs `RETURN-TO-PREV-SCREEN`, `PROCESS-ENTER-KEY`, `SEND-USRLST-SCREEN`, and `RECEIVE-USRLST-SCREEN`.
- **PROCESS-ENTER-KEY** performs `PROCESS-PAGE-FORWARD`.
- **PROCESS-PF7-KEY** performs `PROCESS-PAGE-BACKWARD` and `SEND-USRLST-SCREEN`.
- **PROCESS-PF8-KEY** performs `PROCESS-PAGE-FORWARD` and `SEND-USRLST-SCREEN`.
- **PROCESS-PAGE-FORWARD** performs multiple operations including `STARTBR-USER-SEC-FILE` and `READNEXT-USER-SEC-FILE`.
- **PROCESS-PAGE-BACKWARD** performs similar operations as above but for previous records.
- **SEND-USRLST-SCREEN** performs `POPULATE-HEADER-INFO`.

### Copybooks Used
COCOM01Y, COUSR00, COTTL01Y, CSDAT01Y, CSMSG01Y, CSUSR01Y, DFHAID, DFHBMSCA.

### Notes
- sourceFormat=FIXED
- engine=JsonCli
- copybooks.count=8

### Diagram(s)
*Mindmap View*
```mermaid
mindmap
  COUSR00C
    source
      relpath: app/cbl/COUSR00C.cbl
      sha256: 831433c6ec8306038c85cb86a8307f91dca48c26ef33a997f402187cbd9f4e04
    divisions
      identification
        present: true
      environment
      data
      procedure
    paragraphs
      MAIN-PARA
        performs
          RETURN-TO-PREV-SCREEN
          PROCESS-ENTER-KEY
          SEND-USRLST-SCREEN
          RECEIVE-USRLST-SCREEN
          PROCESS-PF7-KEY
          PROCESS-PF8-KEY
          PROCESS-PAGE-FORWARD
          PROCESS-PAGE-BACKWARD
          STARTBR-USER-SEC-FILE
          READNEXT-USER-SEC-FILE
          VARYING
          INITIALIZE-USER-DATA
          END-IF
          UNTIL
          POPULATE-USER-DATA
          IF
          ENDBR-USER-SEC-FILE
          READPREV-USER-SEC-FILE
          POPULATE-HEADER-INFO
    copybooks_used
      - COCOM01Y
      - COUSR00
      - COTTL01Y
      - CSDAT01Y
      - CSMSG01Y
      - CSUSR01Y
      - DFHAID
      - DFHBMSCA
    notes
      - sourceFormat=FIXED
      - engine=JsonCli
      - copybooks.count=8
```

*Sequence View*
```mermaid
sequenceDiagram
participant A
participant K
participant B
participant E
participant F
participant C
participant D
participant G
participant H
participant M
participant N
participant J
participant I
participant P
participant O
participant L
A->>K: perform RETURN-TO-PREV-SCREEN
A->>B: perform PROCESS-ENTER-KEY
A->>E: perform SEND-USRLST-SCREEN
A->>F: perform RECEIVE-USRLST-SCREEN
A->>B: perform PROCESS-ENTER-KEY
A->>K: perform RETURN-TO-PREV-SCREEN
A->>C: perform PROCESS-PF7-KEY
A->>D: perform PROCESS-PF8-KEY
A->>E: perform SEND-USRLST-SCREEN
B->>G: perform PROCESS-PAGE-FORWARD
C->>H: perform PROCESS-PAGE-BACKWARD
D->>G: perform PROCESS-PAGE-FORWARD
G->>M: perform STARTBR-USER-SEC-FILE
G->>N: perform READNEXT-USER-SEC-FILE
G->>J: perform INITIALIZE-USER-DATA
G->>I: perform POPULATE-USER-DATA
G->>N: perform READNEXT-USER-SEC-FILE
G->>P: perform ENDBR-USER-SEC-FILE
G->>E: perform SEND-USRLST-SCREEN
H->>M: perform STARTBR-USER-SEC-FILE
H->>O: perform READPREV-USER-SEC-FILE
H->>J: perform INITIALIZE-USER-DATA
H->>I: perform POPULATE-USER-DATA
H->>O: perform READPREV-USER-SEC-FILE
H->>P: perform ENDBR-USER-SEC-FILE
H->>E: perform SEND-USRLST-SCREEN
E->>L: perform POPULATE-HEADER-INFO
```

*Flowchart View*
```mermaid
flowchart TD
    A[MAIN-PARA] --> B[RETURN-TO-PREV-SCREEN]
    A --> C[PROCESS-ENTER-KEY]
    A --> D[SEND-USRLST-SCREEN]
    A --> E[RECEIVE-USRLST-SCREEN]
    A --> F[PROCESS-PF7-KEY]
    A --> G[PROCESS-PF8-KEY]
    B --> H[RETURN-TO-PREV-SCREEN]
    C --> I[PROCESS-PAGE-FORWARD]
    F --> J[PROCESS-PAGE-BACKWARD]
    F --> D
    G --> I
    G --> D
    I --> K[STARTBR-USER-SEC-FILE]
    I --> L[READNEXT-USER-SEC-FILE]
    I --> M[VARYING]
    I --> N[INITIALIZE-USER-DATA]
    I --> O[END-IF]
    I --> P[UNTIL]
    I --> L
    I --> Q[POPULATE-USER-DATA]
    I --> R[IF]
    I --> L
    I --> S[ENDBR-USER-SEC-FILE]
    I --> D
    J --> K
    J --> T[READPREV-USER-SEC-FILE]
    J --> M
    J --> N
    J --> O
    J --> P
    J --> T
    J --> Q
    J --> R
    J --> T
    J --> S
    J --> D
    Q --> U[POPULATE-USER-DATA]
    N --> V[INITIALIZE-USER-DATA]
    D --> W[POPULATE-HEADER-INFO]
    W --> D
    K --> D
    L --> D
    T --> D
    S --> D
```

## COTRN00C
This artifact is a COBOL program (`cam.cobol.program`) with source file `app/cbl/COTRN00C.cbl`.
It includes Identification, Environment, Data, and Procedure divisions.

### Paragraphs
- **MAIN-PARA** performs `RETURN-TO-PREV-SCREEN`, `PROCESS-ENTER-KEY`, `SEND-TRNLST-SCREEN`, and `RECEIVE-TRNLST-SCREEN`.
- **PROCESS-ENTER-KEY** performs `SEND-TRNLST-SCREEN` and `PROCESS-PAGE-FORWARD`.
- **PROCESS-PF7-KEY** performs `PROCESS-PAGE-BACKWARD` and `SEND-TRNLST-SCREEN`.
- **PROCESS-PF8-KEY** performs `PROCESS-PAGE-FORWARD` and `SEND-TRNLST-SCREEN`.
- **PROCESS-PAGE-FORWARD** performs multiple operations including `STARTBR-TRANSACT-FILE` and `READNEXT-TRANSACT-FILE`.
- **PROCESS-PAGE-BACKWARD** performs similar operations as above but for previous records.
- **SEND-TRNLST-SCREEN** performs `POPULATE-HEADER-INFO`.

### Copybooks Used
COCOM01Y, COTRN00, COTTL01Y, CSDAT01Y, CSMSG01Y, CVTRA05Y, DFHAID, DFHBMSCA.

### Notes
- sourceFormat=FIXED
- engine=JsonCli
- copybooks.count=8

### Diagram(s)
*Mindmap View*
```mermaid
mindmap
  COTRN00C
    source
      relpath: app/cbl/COTRN00C.cbl
      sha256: 51479f131b4fb300008403f0c4f9fdbde56f22a7fb341c782492da29f0d23bbe
    divisions
      identification
        present: true
      environment
      data
      procedure
    paragraphs
      MAIN-PARA
        performs
          - RETURN-TO-PREV-SCREEN
          - PROCESS-ENTER-KEY
          - SEND-TRNLST-SCREEN
          - RECEIVE-TRNLST-SCREEN
          - PROCESS-PF7-KEY
          - PROCESS-PF8-KEY
          - PROCESS-PAGE-FORWARD
          - PROCESS-PAGE-BACKWARD
          - STARTBR-TRANSACT-FILE
          - READNEXT-TRANSACT-FILE
          - VARYING
          - INITIALIZE-TRAN-DATA
          - END-IF
          - UNTIL
          - POPULATE-TRAN-DATA
          - IF
          - ENDBR-TRANSACT-FILE
          - READPREV-TRANSACT-FILE
          - POPULATE-HEADER-INFO
      PROCESS-ENTER-KEY
      PROCESS-PF7-KEY
      PROCESS-PF8-KEY
      PROCESS-PAGE-FORWARD
      PROCESS-PAGE-BACKWARD
      POPULATE-TRAN-DATA
      INITIALIZE-TRAN-DATA
      RETURN-TO-PREV-SCREEN
      SEND-TRNLST-SCREEN
      RECEIVE-TRNLST-SCREEN
      POPULATE-HEADER-INFO
      STARTBR-TRANSACT-FILE
      READNEXT-TRANSACT-FILE
      READPREV-TRANSACT-FILE
      ENDBR-TRANSACT-FILE
    copybooks_used
      - COCOM01Y
      - COTRN00
      - COTTL01Y
      - CSDAT01Y
      - CSMSG01Y
      - CVTRA05Y
      - DFHAID
      - DFHBMSCA
    notes
      - sourceFormat=FIXED
      - engine=JsonCli
      - copybooks.count=8
```

*Sequence View*
```mermaid
sequenceDiagram
participant A
participant B
participant C
participant D
participant E
participant F
participant G
participant H
participant I
participant L
participant M
participant J
participant K
participant O
participant N
participant P
A->>B: perform RETURN-TO-PREV-SCREEN
A->>C: perform PROCESS-ENTER-KEY
A->>D: perform SEND-TRNLST-SCREEN
A->>E: perform RECEIVE-TRNLST-SCREEN
A->>C: perform PROCESS-ENTER-KEY
A->>B: perform RETURN-TO-PREV-SCREEN
A->>F: perform PROCESS-PF7-KEY
A->>G: perform PROCESS-PF8-KEY
A->>D: perform SEND-TRNLST-SCREEN
C->>D: perform PROCESS-PAGE-FORWARD
C->>D: perform PROCESS-PAGE-FORWARD
C->>H: perform PROCESS-PAGE-BACKWARD
F->>I: perform PROCESS-PAGE-BACKWARD
F->>D: perform SEND-TRNLST-SCREEN
G->>H: perform PROCESS-PAGE-FORWARD
G->>D: perform SEND-TRNLST-SCREEN
H->>L: perform STARTBR-TRANSACT-FILE
H->>M: perform READPREV-TRANSACT-FILE
H->>J: perform INITIALIZE-TRAN-DATA
H->>K: perform POPULATE-TRAN-DATA
H->>O: perform READPREV-TRANSACT-FILE
H->>N: perform ENDBR-TRANSACT-FILE
H->>D: perform SEND-TRNLST-SCREEN
I->>L: perform POPULATE-HEADER-INFO
```

*Flowchart View*
```mermaid
flowchart TD
    A[MAIN-PARA] --> B[RETURN-TO-PREV-SCREEN]
    A --> C[PROCESS-ENTER-KEY]
    A --> D[SEND-TRNLST-SCREEN]
    A --> E[RECEIVE-TRNLST-SCREEN]
    A --> F[PROCESS-PF7-KEY]
    A --> G[PROCESS-PF8-KEY]
    B --> H[RETURN-TO-PREV-SCREEN]
    C --> D
    C --> D
    C --> I[PROCESS-PAGE-FORWARD]
    F --> J[PROCESS-PAGE-BACKWARD]
    F --> D
    G --> I
    G --> D
    I --> K[STARTBR-TRANSACT-FILE]
    I --> L[READNEXT-TRANSACT-FILE]
    I --> M[VARYING]
    I --> N[INITIALIZE-TRAN-DATA]
    I --> O[END-IF]
    I --> P[UNTIL]
    I --> L
    I --> Q[POPULATE-TRAN-DATA]
    I --> R[IF]
    I --> L
    I --> S[ENDBR-TRANSACT-FILE]
    I --> D
    J --> K
    J --> T[READPREV-TRANSACT-FILE]
    J --> M
    J --> N
    J --> O
    J --> P
    J --> T
    J --> Q
    J --> R
    J --> T
    J --> S
    J --> D
    Q --> U[POPULATE-HEADER-INFO]
    D --> U
    D --> U
    K --> D
    L --> D
    T --> D
    S --> D
```

## COSGN00C
This artifact is a COBOL program (`cam.cobol.program`) with source file `app/cbl/COSGN00C.cbl`.
It includes Identification, Environment, Data, and Procedure divisions.

### Paragraphs
- **MAIN-PARA** performs `SEND-SIGNON-SCREEN`, `PROCESS-ENTER-KEY`, `SEND-PLAIN-TEXT`, and `SEND-SIGNON-SCREEN`.
- **PROCESS-ENTER-KEY** performs `SEND-SIGNON-SCREEN`, `SEND-SIGNON-SCREEN`, and `READ-USER-SEC-FILE`.
- **SEND-SIGNON-SCREEN** performs `POPULATE-HEADER-INFO`.
- **READ-USER-SEC-FILE** performs multiple `SEND-SIGNON-SCREEN` operations and includes an I/O READ operation on dataset `DATASET`.

### Copybooks Used
COCOM01Y, COSGN00, COTTL01Y, CSDAT01Y, CSMSG01Y, CSUSR01Y, DFHAID, DFHBMSCA.

### Notes
- sourceFormat=FIXED
- engine=JsonCli
- copybooks.count=8

### Diagram(s)
*Mindmap View*
```mermaid
mindmap
  COSGN00C
    source
      relpath: app/cbl/COSGN00C.cbl
      sha256: 4f901ae6b113eebae60ae1d94b30f8cb9906d031a4