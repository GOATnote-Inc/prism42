import { redirect } from "next/navigation";

// Root of the app — always routes to the dispatcher console. The
// live console IS the product at this URL.
export default function Index() {
  redirect("/prism42");
}
