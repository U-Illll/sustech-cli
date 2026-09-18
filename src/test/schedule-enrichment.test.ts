import assert from "node:assert/strict";
import { test } from "node:test";
import { normalisePersonalScheduleEntry } from "../tis/normalise.js";

test("schedule entry enrichment adds startAt and endAt for known periods", () => {
  const raw = {
    RWH: "2026-2027-1-CS101-001",
    KEY: "xq1_jc1",
    KCDM: "CS101",
    KCMC: "Programming",
    SKJS: "Prof. Zhang",
    SKDD: "一教101",
    SKSJ: "Programming\n[Prof. Zhang]\n[1-16周]\n[一教101]\n[1-2节]",
    SKSJ_EN: "",
    KSJC: 1,
    JSJC: 2,
    ZC: "1111111111111111",
  };

  const entry = normalisePersonalScheduleEntry(raw);
  
  assert.equal(entry.courseCode, "CS101");
  assert.equal(entry.periodStart, 1);
  assert.equal(entry.periodEnd, 2);
  assert.equal(entry.room, "一教101");
});

test("multiple rooms are parsed into rooms array", () => {
  const raw = {
    RWH: "2026-2027-1-PHY201-001",
    KEY: "xq3_jc5",
    KCDM: "PHY201",
    KCMC: "Physics Lab",
    SKJS: "Prof. Li",
    SKDD: "505, 506",
    SKSJ: "Physics Lab\n[Prof. Li]\n[1-8周]\n[505, 506]\n[5-6节]",
    SKSJ_EN: "",
    KSJC: 5,
    JSJC: 6,
    ZC: "11111111",
  };

  const entry = normalisePersonalScheduleEntry(raw);
  
  assert.equal(entry.room, "505, 506");
  assert.deepEqual(entry.rooms, ["505", "506"]);
});

test("single room does not populate rooms array", () => {
  const raw = {
    RWH: "2026-2027-1-CS101-001",
    KEY: "xq1_jc1",
    KCDM: "CS101",
    KCMC: "Programming",
    SKJS: "Prof. Zhang",
    SKDD: "一教101",
    SKSJ: "Programming\n[Prof. Zhang]\n[1-16周]\n[一教101]\n[1-2节]",
    SKSJ_EN: "",
    KSJC: 1,
    JSJC: 2,
    ZC: "1111111111111111",
  };

  const entry = normalisePersonalScheduleEntry(raw);
  
  assert.equal(entry.room, "一教101");
  assert.equal(entry.rooms, undefined);
});

test("entries without period data do not get timestamps", () => {
  const raw = {
    RWH: "2026-2027-1-CS101-001",
    KEY: "unknown_format",
    KCDM: "CS101",
    KCMC: "Programming",
    SKJS: "Prof. Zhang",
    SKDD: "一教101",
    SKSJ: "Programming\n[Prof. Zhang]",
    SKSJ_EN: "",
    ZC: "1111111111111111",
  };

  const entry = normalisePersonalScheduleEntry(raw);
  
  assert.equal(entry.courseCode, "CS101");
  assert.equal(entry.periodStart, undefined);
  assert.equal(entry.periodEnd, undefined);
});
