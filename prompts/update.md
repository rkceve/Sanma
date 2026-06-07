You output JSON only. The ONLY allowed keys are:
version, suns, id, title, planets, mass, satellites, text.

Forbidden keys (do NOT use): label, name, description, summary,
branches, note, status, project, formula, parameters, definition,
notes, children, items, type, content.

Output starts with `{"version":1,"suns":[` and is pure JSON.
No prose, no markdown fences, no commentary.
