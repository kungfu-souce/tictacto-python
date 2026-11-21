from __future__ import annotations

import argparse
import json
import socket
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class Player:
    connection: socket.socket
    address: tuple[str, int]
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    session: GameSession | None = None
    symbol: str | None = None

    def send(self, message: dict[str, Any]) -> bool:
        data = (json.dumps(message) + "\n").encode("utf-8")
        try:
            with self.send_lock:
                self.connection.sendall(data)
        except OSError:
            return False
        return True


@dataclass
class GameSession:
    players: tuple[Player, Player]
    cells: list[list[str]] = field(
        default_factory=lambda: [["" for _ in range(3)] for _ in range(3)]
    )
    turn: str = "X"
    winner: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def is_draw(self) -> bool:
        return self.winner is None and all(cell for row in self.cells for cell in row)

    def has_won(self, symbol: str) -> bool:
        lines = self.cells + [
            [self.cells[row][column] for row in range(3)]
            for column in range(3)
        ]
        lines.extend(
            [
                [self.cells[index][index] for index in range(3)],
                [self.cells[index][2 - index] for index in range(3)],
            ]
        )
        return any(all(cell == symbol for cell in line) for line in lines)


class TicTacToeServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.waiting_players: list[Player] = []
        self.matchmaking_lock = threading.Lock()

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()
            print(f"Tic-Tac-Toe server listening on {self.host}:{self.port}")

            while True:
                connection, address = listener.accept()
                player = Player(connection, address)
                threading.Thread(
                    target=self._handle_player,
                    args=(player,),
                    daemon=True,
                ).start()

    def _handle_player(self, player: Player) -> None:
        print(f"Client connected: {player.address[0]}:{player.address[1]}")
        self._queue_player(player)
        try:
            with player.connection.makefile("r", encoding="utf-8") as reader:
                while True:
                    line = reader.readline(4097)
                    if not line:
                        break
                    if len(line) > 4096:
                        player.send({"type": "error", "message": "Message too large"})
                        break
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        player.send({"type": "error", "message": "Invalid JSON"})
                        continue
                    if not isinstance(message, dict):
                        player.send({"type": "error", "message": "Invalid message"})
                        continue
                    self._handle_message(player, message)
        except (ConnectionError, OSError) as error:
            print(f"Client connection error ({player.address}): {error}")
        finally:
            self._disconnect(player)
            player.connection.close()
            print(f"Client disconnected: {player.address[0]}:{player.address[1]}")

    def _queue_player(self, player: Player) -> None:
        with self.matchmaking_lock:
            self.waiting_players.append(player)
            player.send({"type": "waiting"})
            self._match_waiting_players()

    def _match_waiting_players(self) -> None:
        while len(self.waiting_players) >= 2:
            first = self.waiting_players.pop(0)
            second = self.waiting_players.pop(0)
            session = GameSession((first, second))
            first.session = second.session = session
            first.symbol, second.symbol = "X", "O"
            for player in session.players:
                player.send({"type": "matched", "symbol": player.symbol})
            self._send_state(session)

    def _handle_message(self, player: Player, message: dict[str, Any]) -> None:
        session = player.session
        if session is None:
            player.send({"type": "error", "message": "Waiting for an opponent"})
            return

        with session.lock:
            if message.get("type") == "move":
                row, column = message.get("row"), message.get("column")
                if type(row) is not int or type(column) is not int:
                    player.send({"type": "error", "message": "Invalid move"})
                    return
                if not (0 <= row < 3 and 0 <= column < 3):
                    player.send({"type": "error", "message": "Invalid move"})
                    return
                if session.winner is not None or session.is_draw:
                    player.send({"type": "error", "message": "The game is over"})
                    return
                if player.symbol != session.turn:
                    player.send({"type": "error", "message": "It is not your turn"})
                    return
                if session.cells[row][column]:
                    player.send({"type": "error", "message": "That cell is occupied"})
                    return

                symbol = player.symbol
                session.cells[row][column] = symbol
                if session.has_won(symbol):
                    session.winner = symbol
                elif not session.is_draw:
                    session.turn = "O" if symbol == "X" else "X"
            elif message.get("type") == "reset":
                if session.winner is None and not session.is_draw:
                    player.send({"type": "error", "message": "The game is not over"})
                    return
                session.cells = [["" for _ in range(3)] for _ in range(3)]
                session.turn = "X"
                session.winner = None
            else:
                player.send({"type": "error", "message": "Unknown message type"})
                return

            self._send_state(session)

    def _send_state(self, session: GameSession) -> None:
        for player in session.players:
            player.send(
                {
                    "type": "state",
                    "cells": session.cells,
                    "turn": session.turn,
                    "winner": session.winner,
                    "draw": session.is_draw,
                    "symbol": player.symbol,
                }
            )

    def _disconnect(self, player: Player) -> None:
        with self.matchmaking_lock:
            if player in self.waiting_players:
                self.waiting_players.remove(player)
            session = player.session
            player.session = None
            player.symbol = None
            if session is None:
                return

            opponent = next((other for other in session.players if other is not player), None)
            if opponent is not None and opponent.session is session:
                opponent.session = None
                opponent.symbol = None
                opponent.send({"type": "opponent_left"})
                self.waiting_players.append(opponent)
                opponent.send({"type": "waiting"})
                self._match_waiting_players()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the online Tic-Tac-Toe server.")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on")
    parser.add_argument("--port", type=int, default=5000, help="TCP port to listen on")
    args = parser.parse_args()
    TicTacToeServer(args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
