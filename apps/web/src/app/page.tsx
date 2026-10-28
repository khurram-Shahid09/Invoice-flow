import { redirect } from "next/navigation";

export default function Home() {
  redirect("/inbox"); // proxy.ts sends signed-out visitors to /login first
}
