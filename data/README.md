# data/

`wordlist_en.txt`: the 20,000 most frequent English words, one `word frequency` pair per line, for the local T9 index (spec §6.3).

Source: [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords), `content/2018/en/en_50k.txt` (word counts from OpenSubtitles 2018). The repository is MIT-licensed; the word lists derive from OpenSubtitles and are published as CC BY-SA 4.0, so attribute them if the list is redistributed.

Filtering applied: lowercase letters with at most one inner apostrophe (`don't`, `i'll`), single letters other than `a` and `i` removed, duplicates removed, first 20,000 kept. The list is not profanity-filtered.
