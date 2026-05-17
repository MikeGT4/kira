Du bekommst einen per Spracherkennung transkribierten Text, der in einem Terminal-Fenster landet.

Regeln:
- Wenn der Text wie Konversation klingt (vollstaendiger Satz, Pronomen, Fragepartikel): gib ihn fast unveraendert zurueck. Entferne nur die Satzschluss-Punktuation (Komma, Punkt) und die deutsche Anfuehrungszeichen. Aenderungen sonst minimal.
- Wenn der Text wie ein Shell-Kommando klingt (kurz, Verb-am-Anfang wie `cd`, `ls`, `git`, `docker`, `ssh`, mit Flags/Pfaden): korrigiere offensichtliche Transkriptionsfehler in den Kommando-Tokens.
- NIE Beispiele oder Default-Texte einfuegen. Wenn unklar: einfach den Input fast wortlich zurueckgeben.

Beispiele (NICHT als Output-Vorlage verwenden — nur als Illustration):
- Konversation "Mach mal git pull bitte" -> "Mach mal git pull bitte"
- Konversation "Schau mal in den Logs nach" -> "Schau mal in den Logs nach"
- Kommando "get status" -> "git status"
- Kommando "ssh root att 192 168 1 1" -> "ssh root@192.168.1.1"

Gib NUR den polierten Text zurueck — kein Kommentar, keine Erklaerung, kein Beispiel.

Input:
{text}

Output:
