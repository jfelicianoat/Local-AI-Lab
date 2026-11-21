/** Prevent a late response (including errors) from replacing a newer observation. */
export class LatestRequest {
  private generation = 0;
  private pending = 0;
  invalidate(): void { this.generation++; }
  async run<T>(load: () => Promise<T>, options: { background?: boolean } = {}): Promise<
    { status: "success"; value: T } | { status: "failure"; error: unknown } | { status: "obsolete" }
  > {
    if (options.background && this.pending > 0) return { status: "obsolete" };
    const generation = ++this.generation;
    this.pending++;
    try {
      const value = await load();
      return generation === this.generation ? { status: "success", value } : { status: "obsolete" };
    } catch (error) {
      return generation === this.generation ? { status: "failure", error } : { status: "obsolete" };
    } finally { this.pending--; }
  }
}
