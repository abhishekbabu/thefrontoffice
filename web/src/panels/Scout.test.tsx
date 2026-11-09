import { describe, expect, it } from "vitest";
import { render } from "@/test/render";
import { useJudgeWhenDue } from "@/panels/Scout";

function Judging({ due, scope, judge }: { due: boolean; scope: string; judge: { mutate: () => void; isPending: boolean } }) {
  useJudgeWhenDue(due, scope, judge);
  return null;
}

function counting() {
  const judge = { calls: 0, isPending: false, mutate: () => void judge.calls++ };
  return judge;
}

describe("judging again on arrival", () => {
  it("asks once for a league whose judgment is due, however often the page renders", async () => {
    const judge = counting();
    const page = await render(<Judging due scope="nfl:L1" judge={judge} />);
    await page.rerender(<Judging due scope="nfl:L1" judge={judge} />);

    expect(judge.calls).toBe(1);
  });

  it("asks again for another league", async () => {
    const judge = counting();
    const page = await render(<Judging due scope="nfl:L1" judge={judge} />);
    await page.rerender(<Judging due scope="nfl:L2" judge={judge} />);

    expect(judge.calls).toBe(2);
  });

  it("never asks where the judgment is not due, or one is already running", async () => {
    const judge = counting();
    await render(<Judging due={false} scope="nfl:L1" judge={judge} />);
    await render(<Judging due scope="nfl:L2" judge={{ ...judge, isPending: true }} />);

    expect(judge.calls).toBe(0);
  });
});
