export function roundTitle(day) {
  if (!day) return { title: "—", caption: "KOLO" };
  const label = (day.label || "").trim();
  const regular =
    label.match(/^(?:round|kolo)\s+(\d+)$/i) ||
    label.match(/^(\d+)\.?\s*kolo$/i);
  if (regular) return { title: regular[1], caption: "KOLO" };
  const translated = {
    final: "Finale",
    semifinal: "Polufinale",
    "semi-final": "Polufinale",
    quarterfinal: "Četvrtfinale",
    "bronze medal": "Za treće mesto",
  };
  return {
    title:
      translated[label.toLowerCase()] ||
      label ||
      day.display_label ||
      "Nepoznato kolo",
    caption: "FAZA",
  };
}
