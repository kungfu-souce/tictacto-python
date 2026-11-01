import pygame


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

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Tic-Tac-Toe")
        self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
        self.clock = pygame.time.Clock()
        self.title_font = pygame.font.Font(None, 48)
        self.status_font = pygame.font.Font(None, 32)
        self.mark_font = pygame.font.Font(None, 160)
        self.board = Board()
        self.running = True

    def run(self) -> None:
        while self.running:
            self._handle_events()
            self._draw()
            self.clock.tick(60)

        pygame.quit()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                self.board.reset()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

    def _handle_click(self, position: tuple[int, int]) -> None:
        x, y = position
        if y < self.BOARD_TOP:
            return

        column = x // self.CELL_SIZE
        row = (y - self.BOARD_TOP) // self.CELL_SIZE
        if 0 <= row < 3 and 0 <= column < 3:
            self.board.play(row, column)

    def _draw(self) -> None:
        self.screen.fill(self.BACKGROUND)
        self._draw_header()
        self._draw_grid()
        self._draw_marks()
        pygame.display.flip()

    def _draw_header(self) -> None:
        title = self.title_font.render("Tic-Tac-Toe", True, self.GRID_COLOR)
        self.screen.blit(title, title.get_rect(center=(self.WIDTH // 2, 28)))

        if self.board.winner:
            message = f"{self.board.winner} wins!  Press R to restart"
        elif self.board.is_draw:
            message = "It's a draw!  Press R to restart"
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
    TicTacToeGame().run()