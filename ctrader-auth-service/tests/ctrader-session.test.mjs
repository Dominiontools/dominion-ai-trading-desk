import test from "node:test";
import assert from "node:assert/strict";
import { inMajorSession } from "../lib/ctrader-session.mjs";

test("London session follows local time in winter", () => {
  assert.equal(inMajorSession(new Date("2026-01-15T08:00:00.000Z")), true);
});

test("New York session is recognized after the London session closes", () => {
  assert.equal(inMajorSession(new Date("2026-01-15T17:30:00.000Z")), true);
});

test("session filter rejects the late night outside both sessions", () => {
  assert.equal(inMajorSession(new Date("2026-01-15T23:00:00.000Z")), false);
});

test("London session follows daylight saving time in summer", () => {
  assert.equal(inMajorSession(new Date("2026-07-15T07:30:00.000Z")), true);
});

test("session filter rejects after both summer sessions close", () => {
  assert.equal(inMajorSession(new Date("2026-07-15T21:30:00.000Z")), false);
});

test("invalid dates fail closed", () => {
  assert.equal(inMajorSession(new Date(Number.NaN)), false);
});
