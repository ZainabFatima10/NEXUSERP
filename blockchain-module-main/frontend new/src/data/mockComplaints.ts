// src/data/mockComplaints.ts
//
// The VEMA voice-complaint pipeline (Whisper + Rasa + Google TTS) is listed
// in the FYP report as a planned module — there is no /api/complaints
// backend yet. This seed data lets the User Complaints screen be fully
// interactive and demoable in the meantime. Swap this file out once the
// VEMA backend + endpoints exist; the page component is written so that
// only the data source needs to change.

export type ComplaintCategory = "Power Outage" | "Billing" | "Fault" | "Other";

export interface Complaint {
  id: string;
  ticket: string;
  category: ComplaintCategory;
  description: string;
  area: string;
  createdAt: string; // ISO
  resolved: boolean;
  escalated: boolean;
  resolution?: string;
  resolvedBy?: string;
  resolvedAt?: string;
}

const now = Date.now();
const hoursAgo = (h: number) => new Date(now - h * 3600 * 1000).toISOString();
const minsAgo = (m: number) => new Date(now - m * 60 * 1000).toISOString();

export const SEED_COMPLAINTS: Complaint[] = [
  {
    id: "c1",
    ticket: "TKT-5001",
    category: "Power Outage",
    description: "Complete blackout in G-11/3 since 2 hours. No prior notice given.",
    area: "G-11",
    createdAt: hoursAgo(2),
    resolved: false,
    escalated: false,
  },
  {
    id: "c2",
    ticket: "TKT-5002",
    category: "Billing",
    description: "Overcharged by PKR 12,000 on February bill. Meter reading seems incorrect.",
    area: "F-7",
    createdAt: hoursAgo(9.5),
    resolved: false,
    escalated: false,
  },
  {
    id: "c3",
    ticket: "TKT-5003",
    category: "Power Outage",
    description: "Frequent load shedding beyond scheduled hours in I-8 sector.",
    area: "I-8",
    createdAt: hoursAgo(10.3),
    resolved: false,
    escalated: true,
  },
  {
    id: "c4",
    ticket: "TKT-5004",
    category: "Fault",
    description: "Sparking observed from transformer near F-6 market. Potential fire hazard.",
    area: "F-6",
    createdAt: minsAgo(45),
    resolved: false,
    escalated: true,
  },
  {
    id: "c5",
    ticket: "TKT-4998",
    category: "Power Outage",
    description: "Scheduled maintenance outage lasted 2 hours longer than announced.",
    area: "G-9",
    createdAt: hoursAgo(30),
    resolved: true,
    escalated: false,
    resolution: "Extended due to unexpected cable damage. Completed and restored.",
    resolvedBy: "Engr. Ahmed Khan",
    resolvedAt: hoursAgo(26),
  },
  {
    id: "c6",
    ticket: "TKT-4991",
    category: "Fault",
    description: "Streetlight malfunction on main boulevard H-9.",
    area: "H-9",
    createdAt: hoursAgo(50),
    resolved: true,
    escalated: false,
    resolution: "Replaced faulty MCB and rewired connection.",
    resolvedBy: "Tech. Bilal Raza",
    resolvedAt: hoursAgo(44),
  },
  {
    id: "c7",
    ticket: "TKT-4992",
    category: "Billing",
    description: "Customer charged industrial rate instead of residential.",
    area: "F-10",
    createdAt: hoursAgo(60),
    resolved: true,
    escalated: false,
    resolution: "Tariff category corrected. Refund processed.",
    resolvedBy: "Admin: Sara Malik",
    resolvedAt: hoursAgo(52),
  },
];

export const SLA_HOURS = 4;
