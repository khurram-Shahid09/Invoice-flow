// API shapes used by the dashboard (docs/11-api-spec.md).

export type Role = "clerk" | "approver" | "controller" | "admin";

export interface Org {
  id: string;
  name: string;
  base_currency: string;
  timezone: string;
}

export interface Me {
  id: string;
  email: string;
  name: string;
  memberships: { id: string; roles: Role[]; approval_limit: string | null; org: Org }[];
}
