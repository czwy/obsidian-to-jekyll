# -*- coding: UTF-8 -*-
# obsidian notes -> jekyll posts
#
# python obsidian_to_jekyll.py --help
# python obsidian_to_jekyll.py -w -c -p
# python obsidian_to_jekyll.py --print

import argparse
import os
import pathlib
import sys
import time
import re

import frontmatter                  # pip install python-frontmatter
from git import Repo                # pip install GitPython
from markdown_it import MarkdownIt  # pip install markdown-it-py[linkify,plugins]
from markdown_it.tree import SyntaxTreeNode
import mdit_py_plugins.front_matter as md_frontmatter
import yaml                         # pip install PyYAML
from datetime import datetime
import regex                        # pip install regex

post_subdir = "_posts" # Jekyll posts directory

def eprint(*args, **kwargs):
    """error print"""
    print('\033[93m', file=sys.stderr, end='')
    print(*args, file=sys.stderr, **kwargs, end='')
    print('\033[0m', file=sys.stderr)

class Note:
    """Obsidian Note Class"""

    def __init__(self, nodes, vault_path):
        """
        :param nodes are corresponding markdown-it-py nodes in Posts.md
        :param vault_path is Obsidian vault path
        """
        self.name = ''
        self.file = ''
        self.code = None
        self.post_code = None
        self.frontmatter = None
        self.vault_path = vault_path

        self.parse(nodes)
        if self.file == '':
            eprint("CANNOT GET FILE NAME!!!")
            exit(-1)

        self.read_content()
        self.set_frontmatter()
        self.exec_code()

    def __str__(self):
        return f"Note(name={self.name},file={self.file},frontmatter={self.frontmatter},code={self.code})"

    def find_file(self):
        """find md file of wikilink"""
        if '/' in self.name:
            glob_path = self.name + ".md"
        else:
            glob_path = "**/" + self.name + ".md"
        paths = sorted(pathlib.Path(self.vault_path).glob(glob_path),
                       key=lambda p: len(str(p)))
        if len(paths) >= 1:
            return paths[0].absolute()
        else:
            eprint(f"POST {self.name} NOT FOUND!!!")
            exit(-1)

    def parse(self, nodes):
        """parse markdown-it-py nodes"""
        for node in nodes:
            if node.type == "heading":
                self.name = node.children[0].content[2:-2]
                self.file = self.find_file()
            elif node.type == "fence" and node.info.lower() == "yaml":
                self.frontmatter = yaml.load(node.content, yaml.Loader)
            elif node.type == "fence" and node.info.lower() == "python":
                # the python code normally is executed before content
                # process (in Post class). if the first line of code
                # is `# post`, then the code will be executed after
                # content process.
                if not self.code and not node.content.startswith("# post"):
                    self.code = node.content
                else:
                    self.post_code = node.content
            else:
                eprint(f"UNKNOWN NODE TYPE {node.type} in {self.name}!!!")
                exit(-1)

    def read_content(self):
        """read frontmatter and content of note"""
        with open(self.file, 'r', encoding='utf-8') as f:
            metadata, content = frontmatter.parse(f.read())
            self.content = content
            if not self.frontmatter:
                self.frontmatter = metadata
            elif metadata:
                eprint(f"FILE '{self.name}' HAVE FRONTMATTER!!! "
                        "USE FRONTMATTER IN Post.md INSTEAD")

    def set_frontmatter(self):
        """set note's create date and modified date in frontmatter"""
        def format_time(t):
            return time.strftime("%Y-%m-%d %H:%M:%S +0800", t)
        def same_day(a, b):
            return a.tm_year == b.tm_year and a.tm_yday == b.tm_yday
        ctime = time.localtime(os.path.getctime(self.file))
        mtime = time.localtime(os.path.getmtime(self.file))
        if 'date' not in self.frontmatter:
            self.frontmatter['date'] = format_time(ctime)
        elif type(self.frontmatter['date']) == datetime:
            self.frontmatter['date'] = self.frontmatter['date'].strftime("%Y-%m-%d %H:%M:%S")
        # Chirpy theme key
        if not same_day(ctime, mtime) and 'last_modified_at' not in self.frontmatter:
            self.frontmatter['last_modified_at'] = format_time(mtime)

    def exec_code(self):
        """execute python code in Posts.md"""
        if not self.code:
            return
        ldict = {}
        content = self.content
        exec(self.code, {'content': content}, ldict)
        self.content = ldict['content']

    def render(self) -> str:
        metadata = yaml.dump(self.frontmatter,encoding='utf-8',
                             allow_unicode=True).decode()
        return f"---\n{metadata}---\n\n{self.content}"

class Post:
    """Jekyll Post Class"""

    def __init__(self, blog_path: str, /, note=None, file=None):
        """
        :param blog_path    path of local jekyll repository
        :param note         obsidian note object, used to construct post
                            from obsidian
        :param file         existing jekyll post file path, used to construct
                            post from old jekyll post
        """
        if note and file:
            eprint("Post.__init__ CAN ONLY HAVE NOTE OR FILE!!!")
        if not note and not file:
            eprint("Post.__init__ DON'T HAVE NOTE OR FILE!!!")

        self.blog_path = blog_path
        if note:
            self.frontmatter = note.frontmatter
            self.content = note.content
            self.code = note.post_code
            date_part = note.frontmatter['date'][:10]
            name_part = '-'.join(note.name.lower().split(' '))
            self.file = f"{date_part}-{name_part}.md"
        else:
            self.code = None
            self.file = file
            path = f"{blog_path}/{post_subdir}/{file}"
            with open(path, 'r', encoding='utf-8') as f:
                self.frontmatter, self.content = frontmatter.parse(f.read())
        self.full_path = f"{self.blog_path}/{post_subdir}/{self.file}"

        self.process_image()
        self.process_callouts()
        self.process_obsidian_links()
        self.process_urls()
        self.exec_code()

    def __str__(self):
        return f"Post(file={self.file},frontmatter={self.frontmatter})"

    def set_image_size(self):
        """syntax: ![alt text|100](xxx.png) or ![alt text|100x100](xxx.png)"""
        def get_image_size(alt):
            idx = alt.rfind('|')
            if idx != -1:
                m = re.fullmatch(r"(\d+)(?:x(\d+))?", alt[idx+1:])
                if not m:
                    # is caption
                    return alt, 0, 0
                width = int(m.group(1))
                height = 0 if not m.group(2) else int(m.group(2))
                return alt[:idx], width, height
            else:
                return alt, 0, 0

        lines = self.content.splitlines()
        for i in range(len(lines)):
            imgs = re.finditer(r"!\[(.*)\]\((.+)\)", lines[i])
            pos = 0
            newline = ""
            for img in imgs:
                img_alt, img_width, img_height = get_image_size(img.group(1))
                markups = []
                if img_width:
                    markups.append(f'width="{img_width}"')
                if img_height:
                    markups.append(f'height="{img_height}"')
                if img.start() != 0 or img.end() != len(lines[i]):
                    # inline image
                    markups.append(".normal")
                img_markup = f'![{img_alt}]({img.group(2)})'
                if markups:
                    img_markup += "{: " + ' '.join(markups) + " }"
                newline += lines[i][pos:img.start()]
                newline += img_markup
                pos = img.end()
            newline += lines[i][pos:]
            lines[i] = newline
        self.content = '\n'.join(lines)

    def set_image_caption(self):
        """syntax: ![alt text|caption](xxx.png)
           called after set_image_size()
        """
        def get_caption(alt):
            idx = alt.rfind('|')
            cap = ''
            if idx != -1:
                cap = alt[idx+1:]
                alt = alt[:idx]
            return alt, cap

        capline = []
        newlines = []
        for line in self.content.splitlines():
            imgs = re.finditer(r"!\[(.*)\]\((.+)\)(?:{[^}]*})?", line)
            newline = ""
            pos = 0
            caption = ""
            for img in imgs:
                img_alt, caption = get_caption(img.group(1))
                if caption:
                    if img.start() != 0 or img.end() != len(line):
                        # inline image cannot have caption
                        caption = ''
                    # remove caption from alt text
                    newline += line[pos:img.start(1)] + img_alt
                    pos = img.end(1)
            newlines.append(newline + line[pos:])
            if caption:
                newlines.append(f"_{caption}_")
        self.content = '\n'.join(newlines)

    def process_image(self):
        # set size first
        self.set_image_size()
        self.set_image_caption()

    def process_callouts(self):
        """obsidian callouts to chirpy prompts"""
        cur_type = ''
        newlines = []
        for line in self.content.splitlines():
            if cur_type and not line.strip().startswith('>'):
                newlines.append(f"{{: .prompt-{cur_type} }}")
                cur_type = ''
                newlines.append(line)
                continue
            m = re.fullmatch(r"> \[!(warning|tip|danger|info)\]",
                             line.strip().lower())
            if m:
                cur_type = m.group(1)
            else:
                newlines.append(line)
        if cur_type:
            newlines.append(f"{{: .prompt-{cur_type} }}")
        self.content = '\n'.join(newlines)

    def process_urls(self):
        """replace | in url text to html code &#124; because jekyll's bug"""
        def process_title(title):
            return title.replace('|', '&#124;')
        def process_zotero_url(url):
            if url.startswith('zotero://'):
                eprint("ZOTERO LINK IN ", self.file, url, "!!!")
        lines = self.content.splitlines()
        new_lines = []
        for i in range(len(lines)):
            # include image alt
            urls = re.finditer(r"\[(.*?)\]\((.*?)\)", lines[i])
            newline = ""
            pos = 0
            for url in urls:
                newline += lines[i][pos:url.start(1)] + process_title(url.group(1))
                process_zotero_url(url.group(2))
                pos = url.end(1)
            lines[i] = newline + lines[i][pos:]
        self.content = '\n'.join(lines)

    def process_obsidian_links(self):
        """format url"""
        def sanitize_slug(string: str) -> str:
            pattern = regex.compile(r'[^\p{M}\p{L}\p{Nd}]+', flags=regex.UNICODE)
            slug = regex.sub(pattern, '-', string.strip())
            slug = regex.sub(r'^-|-$', '', slug, flags=regex.IGNORECASE)
            return slug
        """replace [[**]] to Tag <a>"""
        def process_title(title):
            return f"<a href=\"/posts/{sanitize_slug(title.lower())}/\">{title}</a>"
        lines = self.content.splitlines()
        new_lines = []
        for i in range(len(lines)):
            # include obsidian links
            urls = re.finditer(r"\[\[(.*?)\]\]", lines[i])
            newline = ""
            pos = 0
            for url in urls:
                newline += lines[i][pos:url.start()] + process_title(url.group(1))
                pos = url.end()
            lines[i] = newline + lines[i][pos:]
        self.content = '\n'.join(lines)

    def exec_code(self):
        """execute python code in Posts.md"""
        if not self.code:
            return
        ldict = {}
        content = self.content
        exec(self.code, {'content': content}, ldict)
        self.content = ldict['content']

    def render(self) -> str:
        metadata = yaml.dump(self.frontmatter,encoding='utf-8',
                             allow_unicode=True).decode()
        return f"---\n{metadata}---\n\n{self.content}"

    def dump(self):
        with open(self.full_path, 'w', encoding='utf-8') as f:
            f.write(self.render())

#############################################

post_file = r"<obsidian Posts.md path>"
vault_path = r"<obsidian vault path>"
blog_path  = r"<jekyll blog path>"

parser = argparse.ArgumentParser(description='Transform obsidian notes to jekyll posts')
parser.add_argument('-w', '--write',
                    help='Write posts file',
                    action='store_true')
parser.add_argument('-c', '--commit',
                    help='Git commit',
                    action='store_true')
parser.add_argument('-p', '--push',
                    help='Git push',
                    action='store_true')
parser.add_argument('--print',
                    help='Print rendered posts',
                    action='store_true')
parser.add_argument('-f', '--force',
                    help='Force write post files',
                    action='store_true')
parser.add_argument('--commit_msg',
                    action='store')
args = parser.parse_args()

f = open(post_file, encoding='utf-8')
text = f.read()

md = (
    MarkdownIt("commonmark")
        .use(md_frontmatter.front_matter_plugin)
        .enable(["table","list"])
)
tokens = md.parse(text)
root = SyntaxTreeNode(tokens)

# parse posts.md
nodes = []
notes = []
for node in root.children:
    if node.type == 'front_matter':
        continue
    if node.type == "heading":
        if len(nodes) > 0:
            notes.append(Note(nodes, vault_path))
        nodes.clear()
    nodes.append(node)
if len(nodes) > 0:
    notes.append(Note(nodes, vault_path))

# check post update/add and write post file
modified_posts = []
newly_added_posts = []
for note in notes:
    new_post = Post(blog_path, note=note)
    if args.print:
        print(f"---------- {new_post.file} BEGIN ----------")
        print(new_post.render())
        print(f"---------- {new_post.file} END ----------")
    if pathlib.Path(new_post.full_path).is_file():
        old_post = Post(blog_path, file=new_post.file)
        if old_post.frontmatter == new_post.frontmatter:
            if not args.force:
                # content assumes the same since last_modified_at is equal
                continue
        else:
            modified_posts.append(new_post)
    else:
        newly_added_posts.append(new_post)
    if args.write:
        print(f"writing {new_post.file}...")
        new_post.dump()

# commit git repository
if args.commit:
    changed_posts = newly_added_posts + modified_posts
    if len(changed_posts) > 0 or args.commit_msg:
        repo = Repo(blog_path)
        repo.git.add(all=True)
        modified = ','.join([p.file[:-3] for p in modified_posts])
        added = ','.join([p.file[:-3] for p in newly_added_posts])
        commit_msg = ""
        if len(modified_posts) > 0:
            commit_msg += f"Modified posts: {modified}."
        if len(newly_added_posts) > 0:
            if commit_msg:
                commit_msg += " "
            commit_msg += f"Newly added posts: {added}."
        if args.commit_msg:
            if commit_msg:
                commit_msg += " "
            commit_msg += f"{args.commit_msg}"
        print(commit_msg)
        repo.index.commit(commit_msg)
        if args.push:
            for remote in repo.remotes:
                remote.push()