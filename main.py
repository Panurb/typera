from enum import Enum
from configparser import ConfigParser, NoSectionError
import pickle
from collections import defaultdict

import numpy as np
from numpy.linalg import norm
import pygame
from pygame import gfxdraw

# Word list sources:
# https://github.com/davidak/wortliste

FPS = 60
# text, player, enemy, laser, bg
PALETTES = {'default': [(255, 221, 74), (23, 190, 187), (241, 113, 5), (177, 24, 200), (0, 48, 73)],
            'negative': [(0, 34, 181), (232, 65, 68), (14, 142, 250), (78, 231, 55), (255, 207, 182)],
            'autumn': [(243, 188, 46), (212, 91, 81), (156, 39, 6), (95, 84, 38), (96, 60, 20)],
            'winter': [(7, 6, 0), (4, 138, 129), (52, 84, 209), (192, 232, 249), (252, 252, 255)]}
PALETTES = {key: [np.array(x) for x in val] for key, val in PALETTES.items()}
HARD_LIMIT = 50


def key_name(key):
    name = pygame.key.name(key)
    
    if name == ';':
        name = 'ö'
    elif name == "'":
        name = 'ä'
    elif name == '[':
        name = 'å'
        
    return name


def random_unit():
    r = 2 * np.random.uniform(size=2) - 1
    r /= np.linalg.norm(r)
    return r
    
    
def shade(color, darkness):
    return (1 - darkness) * color
    
    
def tint(color, lightness):
    return color + lightness * (255 - color)
    

class State(Enum):
    MENU = 1
    PLAY = 2
    OPTIONS = 3


class Main:
    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 2, 2048)
        pygame.mixer.init()
        pygame.init()
        self.clock = pygame.time.Clock()
        
        self.screen = None
        
        self.state = State.MENU
        
        self.player = Player()
        self.enemies = []
        self.lasers = []
        self.camera = Camera()
        
        self.words = dict()
                
        self.palette = None
        self.difficulty = 'normal'
        self.selection = None
        self.timer = 0.0
        self.score = 0
        self.hits = 0
        self.shots = 0
        self.time = 0.0
        
        self.sounds = dict()
        for sound in ['laser', 'explosion', 'error', 'select']:
            self.sounds[sound] = pygame.mixer.Sound(f'./sound/{sound}.wav')
        pygame.mixer.music.load('./sound/words.mp3')

        try:
            with open('save', 'rb') as f:
                self.high_score = pickle.load(f)
        except FileNotFoundError:
            self.high_score = dict()
        
        self.menu_index = 0
        self.menu_buttons = ['NORMAL', 'HARD', 'OPTIONS', 'QUIT']
        self.options = ['PALETTE', 'LANGUAGE', 'RESOLUTION', 'FULLSCREEN', 'SFX VOLUME', 'MUSIC VOLUME']
        self.options_values = {'PALETTE': list(PALETTES.keys()),
                               'LANGUAGE': ['english', 'deutsch', 'suomi'],
                               'RESOLUTION': ['1280x720', '1920x1080', '2560x1440', '3840x2160'],
                               'FULLSCREEN': ['off', 'on'],
                               'SFX VOLUME': [str(10 * x) for x in range(11)],
                               'MUSIC VOLUME': [str(10 * x) for x in range(11)],
                               }
        self.options_index = {'PALETTE': 0,
                               'LANGUAGE': 0,
                               'RESOLUTION': 0,
                               'FULLSCREEN': 0,
                               'SFX VOLUME': 10,
                               'MUSIC VOLUME': 8,
                             }
                           
        self.config = ConfigParser()
        try:
            self.config.read('config.ini')
            for op in self.options:
                self.options_index[op] = self.options_values[op].index(self.config.get('OPTIONS', op))
        except NoSectionError:
            self.config.add_section('OPTIONS')

        self.apply_options()
        
        pygame.mixer.music.play(-1)

    def load_words(self, path):
        self.words.clear()
        with open(f'./languages/{path}.txt', 'r', encoding='utf-8') as f:
            for line in f.readlines():
                word = line.strip().lower()
                if not word.isalpha():
                    continue
                    
                if len(word) in self.words:
                    self.words[len(word)].append(word)
                else:
                    self.words[len(word)] = [word]
        
    def add_enemy(self):
        used_letters = set()
        for enemy in self.enemies:
            if enemy.word:
                used_letters.add(enemy.word[0])
            
        length = np.random.choice(list(range(5, 11)))
        while True:
            word = np.random.choice(self.words[length])
            if word[0] not in used_letters:
                break
        
        self.enemies.append(Enemy(word))
        
    def options_value(self, option):
        return self.options_values[option][self.options_index[option]]
        
    def apply_options(self):
        res = [int(x) for x in self.options_value('RESOLUTION').split('x')]
        if self.options_value('FULLSCREEN') == 'on':
            self.screen = pygame.display.set_mode(res, pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(res)
        self.camera.zoom = 100 / 720 * res[1]
        self.camera.font = pygame.font.SysFont('Arial', int(28 * self.camera.zoom / 100))
        
        vol = float(self.options_value('SFX VOLUME')) / 100
        for sound in self.sounds.values():
            sound.set_volume(vol)
            
        vol = float(self.options_value('MUSIC VOLUME')) / 100
        pygame.mixer.music.set_volume(vol)
        
        self.load_words(self.options_value('LANGUAGE'))
        
        self.palette = PALETTES[self.options_value('PALETTE')]
        self.camera.color = self.palette[0]
        
        for op in self.options:
            self.config.set('OPTIONS', op, self.options_value(op))
            
        with open('config.ini', 'w') as f:
            self.config.write(f)
            
        if self.options_value('LANGUAGE') not in self.high_score:
            self.high_score[self.options_value('LANGUAGE')] = defaultdict(int)
            
    def save_score(self):
        lan = self.options_value('LANGUAGE')

        self.high_score[lan][self.difficulty] = max(self.score, self.high_score[lan][self.difficulty])
        
        with open('save', 'wb') as f:
            pickle.dump(self.high_score, f)
            
    def new_game(self, difficulty):
        self.state = State.PLAY
        self.timer = 0.0
        self.player.health = 1
        self.score = 0
        self.hits = 0
        self.shots = 0
        self.camera.velocity[:] = 0.0
        self.time = 0.0
        self.player.alive = True
        self.player.direction[:] = [1, 0]
        self.sounds['select'].play()
        self.difficulty = difficulty
        self.selection = None
        
    def end_game(self):
        self.camera.brightness = 0.5
        self.camera.shake(4)
        self.player.damage()
        self.sounds['explosion'].play()
        self.save_score()

    def input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True
                
            if event.type != pygame.KEYDOWN:
                continue

            if self.state is State.MENU:
                if event.key == pygame.K_ESCAPE:
                    return True
                elif event.key == pygame.K_UP:
                    self.menu_index = (self.menu_index - 1) % 4
                    self.sounds['select'].play()
                elif event.key == pygame.K_DOWN:
                    self.menu_index = (self.menu_index + 1) % 4
                    self.sounds['select'].play()
                elif event.key == pygame.K_RETURN:
                    if self.menu_index == 0:
                        self.new_game('normal')
                    elif self.menu_index == 1:
                        if self.high_score[self.options_value('LANGUAGE')]['normal'] >= HARD_LIMIT:
                            self.new_game('hard')
                    elif self.menu_index == 2:
                        self.state = State.OPTIONS
                        self.menu_index = 0
                        self.sounds['select'].play()
                    elif self.menu_index == 3:
                        return True
            elif self.state is State.OPTIONS:
                if event.key == pygame.K_ESCAPE:
                    self.state = State.MENU
                    self.menu_index = 0
                    self.sounds['error'].play()
                elif event.key == pygame.K_RETURN:
                    self.apply_options()
                    self.sounds['select'].play()
                elif event.key == pygame.K_UP:
                    self.menu_index = (self.menu_index - 1) % len(self.options)
                    self.sounds['select'].play()
                elif event.key == pygame.K_DOWN:
                    self.menu_index = (self.menu_index + 1) % len(self.options)
                    self.sounds['select'].play()
                elif event.key == pygame.K_LEFT:
                    sel = self.options_index[self.options[self.menu_index]]
                    vals = self.options_values[self.options[self.menu_index]]
                    self.options_index[self.options[self.menu_index]] = (sel - 1) % len(vals)
                    self.sounds['select'].play()
                elif event.key == pygame.K_RIGHT:
                    sel = self.options_index[self.options[self.menu_index]]
                    vals = self.options_values[self.options[self.menu_index]]
                    self.options_index[self.options[self.menu_index]] = (sel + 1) % len(vals)
                    self.sounds['select'].play()
            elif self.state is State.PLAY:
                if event.key == pygame.K_ESCAPE:
                    self.state = State.MENU
                    self.menu_index = 0
                    self.enemies.clear()
                    self.sounds['error'].play()
                elif self.player.alive:
                    name = key_name(event.key)

                    self.shots += 1
                    
                    if not self.selection:
                        for enemy in self.enemies:
                            if enemy.word and enemy.word[0] == name:
                                self.selection = enemy
                                enemy.selected = True
                                break
                        else:
                            if self.difficulty == 'hard':
                                self.end_game()
                            self.sounds['error'].play()
                                
                    if self.selection:
                        if self.selection.word[0] == name:
                            self.selection.damage()
                            self.lasers.append(Laser(self.selection.position))
                            r = self.selection.position / norm(self.selection.position)
                            self.player.direction = r
                            self.player.debris.append(Debris(1.5 * r * self.player.radius, 0.25 * r, 
                                                             0.5 * self.player.radius, 3))
                            self.camera.shake(0.5)
                            self.hits += 1
                            self.sounds['laser'].play()
                        else:
                            if self.difficulty == 'hard':
                                self.end_game()
                            self.sounds['error'].play()
                            
                        if not self.selection.word:
                            self.camera.brightness = 0.5
                            self.camera.shake(2)
                            self.selection = None
                            self.score += 1
                            self.sounds['explosion'].play()

    def update(self, time_step):
        if self.state is State.MENU:
            pass
        elif self.state is State.OPTIONS:
            pass
        elif self.state is State.PLAY:
            self.time += time_step

            if self.timer <= 0:
                self.add_enemy()
                self.timer = 4.0 + max(0, 12 - 0.2 * self.score)
            else:
                self.timer -= time_step
                
            self.camera.update(time_step)
            
            self.player.update(time_step)

            for enemy in self.enemies:
                if self.player.health:
                    enemy.update(time_step)
                
                    if norm(self.player.position - enemy.position) < enemy.radius + 0.5 * self.player.radius:
                        self.end_game()
                        break
                    
                if not enemy.alive and not enemy.debris:
                    self.enemies.remove(enemy)
            
            for laser in self.lasers:
                laser.update(time_step)
                if norm(laser.start) > norm(laser.target):
                    self.lasers.remove(laser)
        
    def draw(self):
        b = self.camera.brightness
        self.screen.fill((1 - b) * self.palette[4] + b * self.camera.color)
        
        if self.state is State.MENU:
            lan = self.options_value("LANGUAGE")
            
            for i, b in enumerate(self.menu_buttons):
                color = self.palette[0] if i == self.menu_index else self.palette[1]
                
                if b == 'HARD':     
                    if self.high_score[lan]['normal'] >= HARD_LIMIT:
                        self.camera.draw_text(self.screen, color, np.array([self.camera.position[0], -i - 0.3]), 
                                              f'high score: {self.high_score[lan]["hard"]}')
                    else:
                        b = 'LOCKED'
                        self.camera.draw_text(self.screen, color, np.array([self.camera.position[0], -i - 0.3]), 
                                              f'beat {HARD_LIMIT} on normal')
                elif b == 'NORMAL':
                    self.camera.draw_text(self.screen, color, np.array([self.camera.position[0], -i - 0.3]), 
                                          f'high score: {self.high_score[lan]["normal"]}')

                self.camera.draw_text(self.screen, color, np.array([self.camera.position[0], -i]), b)
            
            pos = np.array([self.camera.position[0], 2.0])
            title = 'TYPER: A'
            size = 256
            self.camera.draw_text(self.screen, shade(self.palette[4], 0.2), pos + 0.2 * np.array([1, -1]), title, size)
            self.camera.draw_text(self.screen, self.palette[2], pos + 0.05 * np.array([1, -1]), title, size)
            self.camera.draw_text(self.screen, self.palette[0], pos, title, size)
        elif self.state is State.OPTIONS:
            self.camera.draw_text(self.screen, self.palette[1], self.camera.position + np.array([-5, -3]), 
                                  'ESC: back')
            self.camera.draw_text(self.screen, self.palette[1], self.camera.position + np.array([5, -3]), 
                                  'ENTER: apply')
                                  
            for i, b in enumerate(self.options):
                color = self.palette[0] if i == self.menu_index else self.palette[1]
                self.camera.draw_text(self.screen, color, np.array([self.camera.position[0], 2.5 - i]), b)
                self.camera.draw_text(self.screen, color, np.array([self.camera.position[0], 2.2 - i]),
                                      self.options_value(b))
        elif self.state is State.PLAY:
            for enemy in self.enemies:
                enemy.draw_shadow(self.screen, self.camera, self.palette)
                    
            self.player.draw_shadow(self.screen, self.camera, self.palette)
                
            for laser in self.lasers:
                laser.draw(self.screen, self.camera, self.palette)
                    
            self.player.draw(self.screen, self.camera, self.palette)
                    
            for enemy in self.enemies:
                enemy.draw(self.screen, self.camera, self.palette)
                
            for enemy in self.enemies:
                enemy.draw_text(self.screen, self.camera, self.palette)
                    
            if self.player.health == 0 and not self.player.debris:
                self.selection = None
                self.enemies.clear()
                self.state = State.MENU
                
            self.camera.draw_text(self.screen, self.palette[0], np.array([0.0, -2.4]), f'TIME: {int(self.time / 6)}')
            self.camera.draw_text(self.screen, self.palette[0], np.array([0.0, 2.5]), f'{self.score}', 128)
            acc = int(self.hits / self.shots * 100) if self.shots else 0
            self.camera.draw_text(self.screen, self.palette[0], np.array([0.0, -2.8]), f'ACC: {acc} %')
            self.camera.draw_text(self.screen, self.palette[0], np.array([0.0, -3.2]), f'WPM: {int(360 * self.score / (self.time + 1e-6))}')


    def main_loop(self):
        while True:
            if self.input():
                break
                
            fps = self.clock.get_fps()
            
            self.update(0.1 * 60 / (fps + 1e-6))
            self.draw()
            
            #self.camera.draw_text(self.screen, self.palette[0], 
            #                      self.camera.position + np.array([6, 3.4]), f'{fps:.2f}')
            
            pygame.display.update()
            self.clock.tick(FPS)


class Camera:
    def __init__(self):
        self.origin = np.array([5.0, 0.0])
        self.position = np.array([5.0, 0.0])
        self.zoom = 100
        self.font = pygame.font.SysFont('Arial', int(28))
        self.center = np.array([-1280, 720]) * 0.5 / self.zoom
        self.velocity = np.zeros(2)
        self.brightness = 0.0
        self.color = 255 * np.ones(3)
        
    def shake(self, intensity):
        r = intensity * random_unit()
        self.velocity += r
        
    def update(self, time_step):
        r = self.position - self.origin
        self.velocity += -2 * (5 * r + self.velocity) * time_step
        self.position += self.velocity * time_step
        if norm(self.velocity) < 0.01:
            self.velocity[:] = 0.0
            
        self.brightness = max(0, self.brightness - 0.5  * time_step)

    def world_to_screen(self, position):
        pos = [int(self.zoom * x) for x in position - self.position - self.center]
        pos[1] *= -1
        return pos

    def draw_circle(self, screen, color, position, radius):
        color = (1 - self.brightness) * color + self.brightness * self.color
        rad = int(radius * self.zoom)
        gfxdraw.aacircle(screen, *self.world_to_screen(position), rad, color)
        gfxdraw.filled_circle(screen, *self.world_to_screen(position), rad, color)
        
    def draw_ellipse(self, screen, color, position, width, height, angle=0.0):
        w = int(width * self.zoom)
        h = int(height * self.zoom)
        
        surf = pygame.Surface((3 * w, 3 * h), pygame.SRCALPHA, 32)
        
        color = (1 - self.brightness) * color + self.brightness * self.color
        x, y = surf.get_rect().center
        gfxdraw.aaellipse(surf, x, y, w, h, color)
        gfxdraw.filled_ellipse(surf, x, y, w, h, color)
        
        surf = pygame.transform.rotate(surf, np.rad2deg(angle))
        
        x, y = surf.get_rect().center
        pos = self.world_to_screen(position)
        screen.blit(surf, (pos[0] - x, pos[1] - y))
        
    def draw_text(self, screen, color, position, string, size=28):
        font = self.font if size == 28 else pygame.font.SysFont('Arial', int(size * self.zoom / 100))
        surf = font.render(string, True, color)
        x, y = surf.get_rect().center
        pos = self.world_to_screen(position)
        screen.blit(surf, (pos[0] - x, pos[1] - y))
        
    def draw_line(self, screen, color, start, end, width):
        color = (1 - self.brightness) * color + self.brightness * self.color
        r = end - start
        n = 0.5 * width * np.array([-r[1], r[0]]) / norm(r)
        
        a = start + n
        b = a + r
        c = b - 2 * n
        d = c - r
        
        points = list(map(self.world_to_screen, [a, b, c, d]))
        
        gfxdraw.aapolygon(screen, points, color)
        gfxdraw.filled_polygon(screen, points, color)
        
        self.draw_circle(screen, color, start, 0.5 * width)
        self.draw_circle(screen, color, end, 0.5 * width)
        
            
class Laser:
    def __init__(self, target):
        self.target = target
        self.direction = self.target / norm(self.target)
        self.start = 0.5 * self.direction
        self.end = 2.5 * self.direction
        self.speed = 10.0
        
    def update(self, time_step):
        self.start += self.speed * self.direction * time_step
        self.end += self.speed * self.direction * time_step
        if norm(self.end) > norm(self.target):
            self.end[:] = self.target
        
    def draw(self, screen, camera, palette):
        camera.draw_line(screen, palette[3], self.start, self.end, 0.1)
        camera.draw_line(screen, tint(palette[3], 0.5), self.start, self.end, 0.03)
            
        
class Object:
    def __init__(self, position, radius, color):
        self.position = position.copy()
        self.debris = []
        self.radius = radius
        self.color = color
        self.alive = True
        
    def update(self, time_step):
        for d in self.debris:
            d.update(time_step)
            if d.radius == 0:
                self.debris.remove(d)

    def destroy(self):
        self.alive = False
        for _ in range(5):
            self.debris.append(Debris(self.position, 0.5 * random_unit(), 0.75 * self.radius, 3))
        for _ in range(5):
            self.debris.append(Debris(self.position, 0.5 * random_unit(), 0.75 * self.radius, self.color))
                
    def draw(self, screen, camera, palette):
        if self.alive:
            offset = 0.05 * self.radius * np.array([self.position[0] - 5, self.position[1]])
            camera.draw_circle(screen, palette[self.color], self.position + offset, 0.9 * self.radius)
            camera.draw_circle(screen, tint(palette[self.color], 0.4), self.position + offset, 0.7 * self.radius)
            camera.draw_circle(screen, palette[self.color], self.position + offset, 0.4 * self.radius)

        for d in self.debris:
            d.draw(screen, camera, palette)
            
    def draw_side(self, screen, camera, palette):
        camera.draw_circle(screen, shade(palette[self.color], 0.2), self.position, self.radius)
            
    def draw_shadow(self, screen, camera, palette):
        if self.alive:
            color = 0.8 * np.array(palette[4])
            camera.draw_circle(screen, color, self.position + 0.1 * np.array([1, -1]), 1.1 * self.radius)

        
class Player(Object):
    def __init__(self):
        super().__init__(np.zeros(2), 0.5, 1)
        self.health = 1
        self.direction = np.array([1, 0])
        
    def damage(self):
        self.health -= 1
        
        if not self.health:
            self.destroy()
                
    def draw(self, screen, camera, palette):
        if self.alive:
            self.draw_side(screen, camera, palette)
            
            camera.draw_line(screen, palette[self.color], self.position, self.position + 0.5 * self.direction, 0.5)
            camera.draw_ellipse(screen, shade(palette[self.color], 0.2), self.position + 0.6 * self.direction, 0.1, 0.15, np.arctan2(*self.direction[::-1]))
                        
        super().draw(screen, camera, palette)


class Enemy(Object):
    def __init__(self, word):
        self.word = word
        pos = np.array([12.0, 8 * np.random.uniform() - 4])
        
        super().__init__(pos, len(self.word) / 20, 2)

        self.speed = 2 / len(self.word)
        self.selected = False
        self.velocity = np.zeros(2)
        self.timer = 0.0

    def update(self, time_step):
        if self.alive:
            r = -self.position / norm(self.position)
            self.velocity += r * time_step
            speed = norm(self.velocity)
            if speed > self.speed:
                self.velocity *= self.speed / speed
            self.position += self.velocity * time_step
            
            self.timer = max(0, self.timer - time_step)

        super().update(time_step)
    
    def damage(self):
        self.word = self.word[1:]
        r = self.position / norm(self.position)
        self.velocity += r
        self.timer = 0.5
        
        pos = self.position - r * self.radius
        rad = 0.5 * self.radius
        for _ in range(5):
            self.debris.append(Debris(pos, 0.3 * random_unit(), rad, 3))

        if not self.word:
            self.color = 2
            self.destroy()

    def draw(self, screen, camera, palette):
        if self.alive:
            self.color = 3 if self.timer else 2
            self.draw_side(screen, camera, palette)

        super().draw(screen, camera, palette)
        
    def draw_text(self, screen, camera, palette):
        if self.word:
            color = palette[0] if self.selected else palette[1]
            camera.draw_text(screen, color, self.position - np.array([0, -1.5 * self.radius]), self.word)
            
            
class Debris:
    def __init__(self, position, velocity, radius, color, shading=0.3):
        self.position = position.copy()
        self.velocity = velocity.copy()
        self.radius = radius
        self.color = color
        self.shading = shading
        
    def update(self, time_step):
        self.position += self.velocity * time_step
        self.radius = max(0, self.radius - 0.1 * time_step)
        
    def draw(self, screen, camera, palette):
        camera.draw_circle(screen, shade(palette[self.color], self.shading), self.position, self.radius)
        camera.draw_circle(screen, palette[self.color], self.position + 0.3 * self.radius * np.array([-1, 1]), 
                           0.9 * self.radius)


if __name__ == '__main__':
    main_window = Main()
    main_window.main_loop()
