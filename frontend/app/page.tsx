import { readFileSync } from "node:fs";
import { join } from "node:path";
import Script from "next/script";

export const dynamic = "force-static";

function landingMarkup() {
  const source = readFileSync(join(process.cwd(), "public/reference/index.html"), "utf8");
  const match = source.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  return (match?.[1] ?? "")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/((?:src|href)=["'])assets\//g, "$1/reference/assets/")
    .replaceAll('href="demo/"', 'href="/demo/"')
    .replaceAll('href="motion/', 'href="/reference/motion/');
}

export default function Home() {
  return (
    <>
      <link rel="stylesheet" href="/reference/styles.css" />
      <link rel="stylesheet" href="/reference/features.css" />
      <link rel="stylesheet" href="/reference/mascot.css" />
      <div dangerouslySetInnerHTML={{ __html: landingMarkup() }} />
      <Script src="/reference/script.js" strategy="afterInteractive" />
      <Script src="/reference/features.js" strategy="afterInteractive" />
      <Script src="/reference/mascot.js" strategy="afterInteractive" />
    </>
  );
}
