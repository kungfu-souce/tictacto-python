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
    WIDTH = 640
    HEIGHT = 870
    BOARD_LEFT = 50
    BOARD_TOP = 250
    CELL_SIZE = 180
    BOARD_GAP = 12
    BACKGROUND = (12, 18, 34)
    PANEL_COLOR = (20, 29, 49)
    CELL_COLOR = (27, 39, 63)
    CELL_HOVER = (36, 52, 81)
    TEXT_COLOR = (237, 243, 255)
    MUTED_COLOR = (145, 161, 187)
    X_COLOR = (74, 216, 255)
    O_COLOR = (255, 190, 92)
    ACCENT_COLOR = (119, 112, 255)

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
        self.title_font = pygame.font.Font(None, 58)
        self.subtitle_font = pygame.font.Font(None, 24)
        self.status_font = pygame.font.Font(None, 30)
        self.player_font = pygame.font.Font(None, 24)
        self.symbol_font = pygame.font.Font(None, 42)
        self.footer_font = pygame.font.Font(None, 22)
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
        board_width = self.CELL_SIZE * 3
        board_height = self.CELL_SIZE * 3
        if not (
            self.BOARD_LEFT <= x < self.BOARD_LEFT + board_width
            and self.BOARD_TOP <= y < self.BOARD_TOP + board_height
        ):
            return

        column = (x - self.BOARD_LEFT) // self.CELL_SIZE
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
        self._draw_background()
        self._draw_header()
        self._draw_player_cards()
        self._draw_status()
        self._draw_board()
        self._draw_marks()
        self._draw_footer()
        pygame.display.flip()

    def _draw_background(self) -> None:
        for center, radius, color in (
            ((30, 95), 130, (18, 31, 56)),
            ((610, 700), 170, (19, 28, 54)),
            ((570, 80), 82, (24, 27, 57)),
        ):
            pygame.draw.circle(self.screen, color, center, radius)

    def _draw_header(self) -> None:
        title = self.title_font.render("TIC TAC TOE", True, self.TEXT_COLOR)
        self.screen.blit(title, title.get_rect(center=(self.WIDTH // 2, 52)))
        subtitle_text = (
            "ONLINE MATCH" if self.online else "THE CLASSIC, REIMAGINED"
        )
        subtitle = self.subtitle_font.render(
            subtitle_text, True, self.MUTED_COLOR
        )
        self.screen.blit(
            subtitle, subtitle.get_rect(center=(self.WIDTH // 2, 91))
        )

    def _draw_player_cards(self) -> None:
        card_y = 132
        card_width = 260
        card_height = 66
        card_gap = 20
        players = (("X", self.X_COLOR), ("O", self.O_COLOR))
        for index, (symbol, color) in enumerate(players):
            if not self.online:
                label = f"PLAYER {index + 1}"
            elif self.player_symbol is None:
                label = f"PLAYER {symbol}"
            else:
                label = "YOU" if symbol == self.player_symbol else "OPPONENT"
            left = 40 + index * (card_width + card_gap)
            is_turn = self.board.current_player == symbol and (
                not self.online or self.player_symbol is not None
            )
            card_color = (28, 42, 67) if is_turn else self.PANEL_COLOR
            pygame.draw.rect(
                self.screen,
                card_color,
                (left, card_y, card_width, card_height),
                border_radius=18,
            )
            if is_turn:
                pygame.draw.rect(
                    self.screen,
                    color,
                    (left, card_y, card_width, card_height),
                    width=2,
                    border_radius=18,
                )
            symbol_image = self.symbol_font.render(symbol, True, color)
            self.screen.blit(
                symbol_image,
                symbol_image.get_rect(midleft=(left + 20, card_y + 34)),
            )
            label_image = self.player_font.render(
                label, True, self.TEXT_COLOR if is_turn else self.MUTED_COLOR
            )
            self.screen.blit(
                label_image,
                label_image.get_rect(midleft=(left + 74, card_y + 33)),
            )
            if is_turn:
                pygame.draw.circle(
                    self.screen, color, (left + card_width - 20, card_y + 33), 5
                )

    def _status_message(self) -> tuple[str, tuple[int, int, int]]:
        if self.online and self.player_symbol is None:
            return self.network_status, self.MUTED_COLOR
        if self.online and self.notification is not None:
            return self.notification, (255, 145, 145)
        if self.board.winner:
            if not self.online:
                return f"{self.board.winner} WINS!  Press R to play again", (
                    self.X_COLOR
                    if self.board.winner == "X"
                    else self.O_COLOR
                )
            if self.board.winner == self.player_symbol:
                return (
                    "YOU WIN!  Press R to play again",
                    self.X_COLOR if self.player_symbol == "X" else self.O_COLOR,
                )
            return "OPPONENT WINS  |  Press R to play again", self.O_COLOR
        if self.board.is_draw:
            return "IT'S A DRAW  |  Press R to play again", self.TEXT_COLOR
        if self.online:
            if self.player_symbol == self.board.current_player:
                return "YOUR TURN", self.X_COLOR if self.player_symbol == "X" else self.O_COLOR
            return "OPPONENT'S TURN", self.MUTED_COLOR
        return f"{self.board.current_player}'S TURN  |  Press R to restart", (
            self.X_COLOR if self.board.current_player == "X" else self.O_COLOR
        )

    def _draw_status(self) -> None:
        message, color = self._status_message()
        text = self.status_font.render(message, True, color)
        max_width = self.WIDTH - 56
        if text.get_width() > max_width:
            text = pygame.transform.smoothscale(
                text, (max_width, text.get_height())
            )
        self.screen.blit(text, text.get_rect(center=(self.WIDTH // 2, 222)))

    def _draw_board(self) -> None:
        board_rect = pygame.Rect(
            self.BOARD_LEFT - 4,
            self.BOARD_TOP - 4,
            self.CELL_SIZE * 3 + 8,
            self.CELL_SIZE * 3 + 8,
        )
        pygame.draw.rect(
            self.screen, (16, 24, 42), board_rect, border_radius=28
        )
        mouse_x, mouse_y = pygame.mouse.get_pos()
        can_play = (
            self.board.winner is None
            and not self.board.is_draw
            and (not self.online or self.player_symbol == self.board.current_player)
        )
        for row in range(3):
            for column in range(3):
                left = self.BOARD_LEFT + column * self.CELL_SIZE
                top = self.BOARD_TOP + row * self.CELL_SIZE
                cell_rect = pygame.Rect(
                    left + self.BOARD_GAP // 2,
                    top + self.BOARD_GAP // 2,
                    self.CELL_SIZE - self.BOARD_GAP,
                    self.CELL_SIZE - self.BOARD_GAP,
                )
                hovered = cell_rect.collidepoint(mouse_x, mouse_y)
                color = (
                    self.CELL_HOVER
                    if hovered and can_play and not self.board.cells[row][column]
                    else self.CELL_COLOR
                )
                pygame.draw.rect(
                    self.screen, color, cell_rect, border_radius=22
                )
                if hovered and can_play and not self.board.cells[row][column]:
                    pygame.draw.rect(
                        self.screen,
                        self.ACCENT_COLOR,
                        cell_rect,
                        width=2,
                        border_radius=22,
                    )

    def _draw_footer(self) -> None:
        hint = "CLICK A TILE TO PLAY     •     PRESS R TO RESTART"
        if self.online:
            hint = "MAKE YOUR MOVE     •     PRESS R AFTER THE GAME"
        text = self.footer_font.render(hint, True, self.MUTED_COLOR)
        self.screen.blit(text, text.get_rect(center=(self.WIDTH // 2, 830)))

    def _draw_marks(self) -> None:
        for row in range(3):
            for column in range(3):
                mark = self.board.cells[row][column]
                if not mark:
                    continue

                color = self.X_COLOR if mark == "X" else self.O_COLOR
                center = (
                    self.BOARD_LEFT + column * self.CELL_SIZE + self.CELL_SIZE // 2,
                    self.BOARD_TOP + row * self.CELL_SIZE + self.CELL_SIZE // 2,
                )
                radius = 48
                stroke = 12
                if mark == "X":
                    start_a = (center[0] - radius, center[1] - radius)
                    end_a = (center[0] + radius, center[1] + radius)
                    start_b = (center[0] + radius, center[1] - radius)
                    end_b = (center[0] - radius, center[1] + radius)
                    for start, end in ((start_a, end_a), (start_b, end_b)):
                        pygame.draw.line(self.screen, color, start, end, stroke)
                        pygame.draw.circle(self.screen, color, start, stroke // 2)
                        pygame.draw.circle(self.screen, color, end, stroke // 2)
                else:
                    pygame.draw.circle(
                        self.screen, color, center, radius, width=stroke
                    )


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