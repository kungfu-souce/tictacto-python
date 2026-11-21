import argparse
import json
import queue
import socket
import threading

import pygame


class OnlineClient:
    """Send moves to the server and queue incoming game updates."""

    def __init__(self, host: str, port: int) -> None:
        self.connection = socket.create_connection((host, port), timeout=5)
        self.connection.settimeout(None)
        self.incoming: queue.Queue[dict[str, object]] = queue.Queue()
        self.send_lock = threading.Lock()
        self.reader = self.connection.makefile("r", encoding="utf-8")
        self.reader_thread = threading.Thread(target=self._read_messages, daemon=True)
        self.reader_thread.start()

    def _read_messages(self) -> None:
        try:
            for line in self.reader:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self.incoming.put(
                        {"type": "error", "message": "ได้รับข้อมูลไม่ถูกต้องจากเซิร์ฟเวอร์"}
                    )
                    break
                if isinstance(message, dict):
                    self.incoming.put(message)
        except OSError:
            self.incoming.put({"type": "disconnected"})
        else:
            self.incoming.put({"type": "disconnected"})

    def send(self, message: dict[str, int | str]) -> bool:
        try:
            with self.send_lock:
                self.connection.sendall(
                    (json.dumps(message) + "\n").encode("utf-8")
                )
        except OSError:
            self.incoming.put({"type": "disconnected"})
            return False
        return True

    def close(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()


class Board:
    """Keep track of the board and the rules of the game."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cells = [["" for _ in range(3)] for _ in range(3)]
        self.current_player = "X"
        self.winner: str | None = None

    @property
    def is_draw(self) -> bool:
        return self.winner is None and all(cell for row in self.cells for cell in row)

    def play(self, row: int, column: int) -> bool:
        if self.winner is not None or self.is_draw or self.cells[row][column]:
            return False

        self.cells[row][column] = self.current_player
        if self._has_won(self.current_player):
            self.winner = self.current_player
        elif not self.is_draw:
            self.current_player = "O" if self.current_player == "X" else "X"
        return True

    def _has_won(self, player: str) -> bool:
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
        return any(all(cell == player for cell in line) for line in lines)


class TicTacToeGame:
    WIDTH = 600
    HEIGHT = 700
    BOARD_TOP = 100
    CELL_SIZE = 200
    BACKGROUND = (245, 247, 250)
    GRID_COLOR = (45, 55, 72)
    X_COLOR = (220, 70, 70)
    O_COLOR = (55, 115, 210)

    def __init__(self, server_address: tuple[str, int] | None = None) -> None:
        self.network = (
            OnlineClient(*server_address) if server_address is not None else None
        )
        pygame.init()
        self.online = server_address is not None
        pygame.display.set_caption(
            "Tic-Tac-Toe Online" if self.online else "Tic-Tac-Toe"
        )
        self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
        self.clock = pygame.time.Clock()
        self.title_font = pygame.font.Font(None, 48)
        self.status_font = pygame.font.Font(None, 32)
        self.mark_font = pygame.font.Font(None, 160)
        self.board = Board()
        self.running = True
        self.player_symbol: str | None = None
        self.network_status = "Connecting..."
        self.notification: str | None = None

    def run(self) -> None:
        while self.running:
            self._process_network_messages()
            self._handle_events()
            self._draw()
            self.clock.tick(60)

        if self.network is not None:
            self.network.close()
        pygame.quit()

    def _process_network_messages(self) -> None:
        if self.network is None:
            return

        while True:
            try:
                message = self.network.incoming.get_nowait()
            except queue.Empty:
                return

            message_type = message.get("type")
            if message_type == "waiting":
                self.board.reset()
                self.player_symbol = None
                self.network_status = "Waiting for an opponent..."
                self.notification = None
            elif message_type == "matched":
                symbol = message.get("symbol")
                if symbol in ("X", "O"):
                    self.player_symbol = symbol
                    self.network_status = f"You are {symbol}"
                    self.notification = None
            elif message_type == "state":
                cells = message.get("cells")
                turn = message.get("turn")
                winner = message.get("winner")
                symbol = message.get("symbol")
                valid_cells = (
                    isinstance(cells, list)
                    and len(cells) == 3
                    and all(
                        isinstance(row, list)
                        and len(row) == 3
                        and all(cell in ("", "X", "O") for cell in row)
                        for row in cells
                    )
                )
                if (
                    valid_cells
                    and turn in ("X", "O")
                    and winner in (None, "X", "O")
                    and symbol in ("X", "O")
                ):
                    self.board.cells = cells
                    self.board.current_player = turn
                    self.board.winner = winner
                    self.player_symbol = symbol
                    self.network_status = "Connected"
                    self.notification = None
            elif message_type == "opponent_left":
                self.player_symbol = None
                self.network_status = "Opponent disconnected"
                self.board.reset()
            elif message_type == "disconnected":
                self.player_symbol = None
                self.network_status = "Disconnected from server"
            elif message_type == "error":
                error = message.get("message")
                if isinstance(error, str):
                    self.notification = error

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                if self.network is None:
                    self.board.reset()
                elif self.board.winner is not None or self.board.is_draw:
                    self.network.send({"type": "reset"})
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

    def _handle_click(self, position: tuple[int, int]) -> None:
        x, y = position
        if y < self.BOARD_TOP:
            return

        column = x // self.CELL_SIZE
        row = (y - self.BOARD_TOP) // self.CELL_SIZE
        if 0 <= row < 3 and 0 <= column < 3:
            if self.network is None:
                self.board.play(row, column)
            elif (
                self.player_symbol == self.board.current_player
                and self.board.winner is None
                and not self.board.is_draw
            ):
                self.network.send(
                    {"type": "move", "row": row, "column": column}
                )

    def _draw(self) -> None:
        self.screen.fill(self.BACKGROUND)
        self._draw_header()
        self._draw_grid()
        self._draw_marks()
        pygame.display.flip()

    def _draw_header(self) -> None:
        title = self.title_font.render("Tic-Tac-Toe", True, self.GRID_COLOR)
        self.screen.blit(title, title.get_rect(center=(self.WIDTH // 2, 28)))

        if self.online and self.player_symbol is None:
            message = self.network_status
        elif self.online and self.notification is not None:
            message = self.notification
        elif self.board.winner:
            message = f"{self.board.winner} wins!  Press R to restart"
        elif self.board.is_draw:
            message = "It's a draw!  Press R to restart"
        elif self.online:
            message = (
                f"Your turn ({self.player_symbol})"
                if self.player_symbol == self.board.current_player
                else f"Opponent's turn ({self.board.current_player})"
            )
        else:
            message = f"{self.board.current_player}'s turn  |  Press R to restart"

        status = self.status_font.render(message, True, self.GRID_COLOR)
        self.screen.blit(status, status.get_rect(center=(self.WIDTH // 2, 70)))

    def _draw_grid(self) -> None:
        for index in (1, 2):
            x = index * self.CELL_SIZE
            y = self.BOARD_TOP + index * self.CELL_SIZE
            pygame.draw.line(
                self.screen, self.GRID_COLOR,
                (x, self.BOARD_TOP), (x, self.HEIGHT), 6,
            )
            pygame.draw.line(
                self.screen, self.GRID_COLOR,
                (0, y), (self.WIDTH, y), 6,
            )

    def _draw_marks(self) -> None:
        for row in range(3):
            for column in range(3):
                mark = self.board.cells[row][column]
                if not mark:
                    continue

                color = self.X_COLOR if mark == "X" else self.O_COLOR
                image = self.mark_font.render(mark, True, color)
                center = (
                    column * self.CELL_SIZE + self.CELL_SIZE // 2,
                    self.BOARD_TOP + row * self.CELL_SIZE + self.CELL_SIZE // 2,
                )
                self.screen.blit(image, image.get_rect(center=center))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Play Tic-Tac-Toe.")
    parser.add_argument(
        "--server",
        metavar="HOST",
        help="Connect to an online server instead of playing locally",
    )
    parser.add_argument("--port", type=int, default=5000, help="Server TCP port")
    args = parser.parse_args()

    try:
        TicTacToeGame(
            (args.server, args.port) if args.server is not None else None
        ).run()
    except OSError as error:
        parser.error(f"Could not connect to the server: {error}")