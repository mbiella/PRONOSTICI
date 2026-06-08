# ⚽ GoldenBet — Pronostici Calcio

Applicazione web per gestire pronostici calcistici con backoffice admin.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Apri il browser su: http://localhost:5000

## Credenziali Admin di Default

- **Username:** admin
- **Password:** admin123

## Funzionalità

### Backoffice Admin
- Crea giornate con data e partite
- Apri/chiudi giornate (quando chiusa gli utenti non possono più votare)
- Inserisci risultati (1, X, 2) per ogni partita
- Calcola automaticamente i punti per ogni utente
- Visualizza chi ha inserito cosa con evidenziazione pronostici corretti
- Classifica per giornata e generale

### Frontend Utenti
- Registrazione e login
- Selezione pronostici (1, X, 2) per le partite delle giornate aperte
- Visualizzazione classifica generale

## Struttura DB (SQLite)

- `utenti` — username, password, is_admin
- `giornate` — nome, data, chiusa
- `partite` — squadra_casa, squadra_ospite, risultato, giornata_id
- `pronostici` — utente_id, partita_id, pronostico (1/X/2)
- `classifica` — utente_id, giornata_id, punti
