import type { Metadata } from "next";

import { AuthForm } from "../auth-form";

export const metadata: Metadata = { title: "Create a workspace" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="mb-5 text-lg font-semibold">Create a workspace</h1>
      <AuthForm mode="register" />
    </>
  );
}
