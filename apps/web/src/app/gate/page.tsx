import type { Metadata } from "next";

export const metadata: Metadata = { title: "Password" };

export default async function Gate({ searchParams }: { searchParams: Promise<{ next?: string; wrong?: string }> }) {
  const { next = "/", wrong } = await searchParams;
  return (
    <main style={{ maxWidth: 420, margin: "12vh auto", padding: "0 16px" }}>
      <div className="card pad-lg">
        <h1 style={{ marginTop: 0, fontSize: 24 }}>Landfall</h1>
        <p className="muted">This demo is protected. Enter the password you were given to continue.</p>
        <form method="post" action="/gate/login" className="stack" aria-label="Password">
          <input type="hidden" name="next" value={next} />
          <label>
            Password
            <input name="password" type="password" autoComplete="current-password" required autoFocus style={{ display: "block", width: "100%", marginTop: 6, padding: "10px 12px", font: "inherit", border: "1px solid var(--line-strong)", borderRadius: 8 }} />
          </label>
          {wrong ? <p role="alert" style={{ color: "var(--orange-ink)", margin: 0 }}>That password is not right. Try again.</p> : null}
          <button type="submit" className="btn btn-primary">Continue</button>
        </form>
      </div>
    </main>
  );
}
