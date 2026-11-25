function minutesInZone(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const hour = Number(parts.find((part) => part.type === "hour")?.value);
  const minute = Number(parts.find((part) => part.type === "minute")?.value);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return -1;
  return hour * 60 + minute;
}

export function inMajorSession(now) {
  if (!(now instanceof Date) || !Number.isFinite(now.getTime())) return false;
  const london = minutesInZone(now, "Europe/London");
  const newYork = minutesInZone(now, "America/New_York");
  const inLondon = london >= 8 * 60 && london < 17 * 60;
  const inNewYork = newYork >= 8 * 60 && newYork < 17 * 60;
  return inLondon || inNewYork;
}
