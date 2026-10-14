"""Terminal client for trying the coach:  python -m chesscoach.play [--color white] [--rating 1000]

Commands at the prompt: a move in SAN or UCI, `hint`, `takeback` (after an interrupt), `resume`,
`quit`. Draft (unreviewed) concept text is only shown with --dev, per AGENTS rule 2.
"""
from __future__ import annotations

import argparse
import os
import random

import chess


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--color", default="white", choices=["white", "black"])
    ap.add_argument("--rating", type=int, default=1000, help="your rating; sets band and bot strength")
    ap.add_argument("--mode", default="standard", choices=["guided", "standard", "silent"])
    ap.add_argument("--dev", action="store_true", help="show draft (unreviewed) coaching text")
    args = ap.parse_args()
    if args.dev:
        os.environ["CHESSCOACH_ALLOW_UNREVIEWED"] = "1"

    from chesscoach.analysis.analyzer import Analyzer
    from chesscoach.analysis.engine import EnginePool
    from chesscoach.concepts.registry import Registry
    from chesscoach.learner.bands import band_for
    from chesscoach.policy.policy import CoachingPolicy, CoachSettings, LearnerView
    from chesscoach.session import GameSession
    from chesscoach.sparring.bot import OFFSET_START, BotConfig, SparringBot, bot_target
    from chesscoach.sparring.human_model import load_default
    from chesscoach.sparring.steering import LessonScorer

    reg = Registry.load()
    if not len(reg):
        print("No approved concepts: the coach will only use approved fallback text (run with --dev to see drafts).")
    band = band_for(args.rating)
    pool = EnginePool()
    an = Analyzer(pool, live=True)
    bot = SparringBot(load_default(pool), pool, BotConfig(bot_target(args.rating, OFFSET_START), args.rating),
                      random.Random(), lesson_score=LessonScorer(an, reg, band))
    pol = CoachingPolicy(reg, CoachSettings(mode=args.mode), LearnerView(band=band))
    s = GameSession(an, reg, bot, pol, args.color, band)
    first = s.start()
    if first:
        print(f"Bot: {first.move}")
    try:
        while not s.board.is_game_over():
            print(s.board.unicode(invert_color=True, borders=False, orientation=args.color == "white"))
            pre = s.pre_move_prompt()
            if pre:
                print(f"Coach: {pre.text}")
            cmd = input("> ").strip()
            if cmd == "quit":
                break
            if cmd == "hint":
                h = s.hint()
                print(f"Coach: {h.text}" if h else "Coach: no hint here.")
                continue
            if cmd == "takeback":
                s.takeback()
                continue
            if cmd == "resume":
                bm = s.resume()
                print(f"Bot: {bm.move}")
                continue
            try:
                mv = s.board.parse_san(cmd)
            except ValueError:
                try:
                    mv = chess.Move.from_uci(cmd)
                except ValueError:
                    print("Unknown move or command.")
                    continue
            if not s.board.is_legal(mv):
                print("Illegal move.")
                continue
            r = s.player_move(mv.uci())
            if r.event:
                print(f"Coach: {r.event.text}")
            if r.waiting_for_takeback:
                print("(type `takeback` to try again, `hint` for more, or `resume` to keep your move)")
            if r.bot_move:
                print(f"Bot: {r.bot_san}")
        print("Game over:", s.board.result(claim_draw=True))
    finally:
        pool.close()


if __name__ == "__main__":
    main()
