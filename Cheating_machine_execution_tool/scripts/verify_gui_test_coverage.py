"""Conservative AST preflight for test GUI ownership; never imports test modules.

Static checks cover supported fixture patterns. The strict runner additionally
blocks dynamically resolved Tk constructors before they enter native code.
"""
import ast
from pathlib import Path
import sys
import textwrap


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''


class Coverage:
    qt_mode = False
    scope_decorator = 'tk_test_windows.requires_offscreen'

    def __init__(self, root):
        self.root = Path(root)
        self.modules = {}
        self.functions = {}
        self.classes = {}
        self.errors = []
        self.entries = []
        self.gui_classes = {'tkinter.Tk', 'tkinter.Toplevel'}
        self.installed_classes = set()
        self.required = set()

    def resolve(self, node, aliases):
        name = dotted(node)
        head, dot, tail = name.partition('.')
        return aliases.get(head, head) + (dot + tail if dot else '')

    def is_gui(self, name):
        return name in self.gui_classes or name.endswith('.loadtk')

    def load(self):
        # Source classes are inspected only to identify Tk-derived entry points.
        paths = list((self.root / 'tests').rglob('*.py'))
        for folder in ('src', 'line_check_assistant'):
            paths.extend((self.root / folder).rglob('*.py'))
        for path in sorted(paths):
            relative = path.relative_to(self.root).as_posix()
            if '__pycache__' in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=relative)
            except (SyntaxError, UnicodeError) as exc:
                self.errors.append(f'{relative}: cannot parse source: {exc}')
                continue
            module = relative[:-3].replace('/', '.')
            if module.startswith('tests.'):
                module = module[6:]
            aliases = {}
            for item in ast.walk(tree):
                if isinstance(item, ast.Import):
                    for alias in item.names:
                        aliases[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
                elif isinstance(item, ast.ImportFrom):
                    for alias in item.names:
                        aliases[alias.asname or alias.name] = (item.module or '') + '.' + alias.name
            self.modules[module] = (relative, tree, aliases)
            for item in tree.body:
                if isinstance(item, ast.ClassDef):
                    name = module + '.' + item.name
                    self.classes[name] = (item, module)
                    aliases[item.name] = name
                    for method in item.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.functions[name + '.' + method.name] = (method, module, name)
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = module + '.' + item.name
                    aliases[item.name] = name
                    self.functions[name] = (item, module, '')
        changed = True
        while changed:
            changed = False
            for name, (node, module) in self.classes.items():
                aliases = self.modules[module][2]
                if name not in self.gui_classes and any(self.resolve(base, aliases) in self.gui_classes for base in node.bases):
                    self.gui_classes.add(name)
                    changed = True

    def method(self, cls, method, seen=None):
        seen = set() if seen is None else seen
        if cls in seen or cls not in self.classes:
            return None
        seen.add(cls)
        name = cls + '.' + method
        if name in self.functions:
            return name
        node, module = self.classes[cls]
        for base in node.bases:
            found = self.method(self.resolve(base, self.modules[module][2]), method, seen)
            if found:
                return found
        return None

    def error(self, relative, node, message):
        self.errors.append(f'{relative}:{node.lineno}: {message}')

    def fixture_install(self, statement, aliases):
        calls = []
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            calls = [statement.value]
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.Call):
            calls = [statement.value]
        return any(self.resolve(call.func, aliases) == 'tk_test_windows.install_offscreen_windows'
                   or (isinstance(call.func, ast.Attribute) and call.func.attr == 'enter_context'
                       and call.args and self.scope_context(call.args[0], aliases)) for call in calls)

    def scope_context(self, node, aliases):
        return isinstance(node, ast.Call) and self.resolve(node.func, aliases) == 'tk_test_windows.OffscreenTkWindows'

    def mock_context(self, node, aliases):
        if not isinstance(node, ast.Call):
            return set()
        name = self.resolve(node.func, aliases)
        if name == 'unittest.mock.patch' and node.args and isinstance(node.args[0], ast.Constant):
            target = node.args[0].value
            if isinstance(target, str):
                return {target}
        if name == 'unittest.mock.patch.object' and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            return {self.resolve(node.args[0], aliases) + '.' + str(node.args[1].value)}
        return set()

    def walk(self, statements, module, cls='', protected=False, mocks=frozenset(), emit=True):
        relative, _tree, aliases = self.modules[module]
        state = protected
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                inner = state
                inner_mocks = set(mocks)
                for item in statement.items:
                    inner |= self.scope_context(item.context_expr, aliases)
                    inner_mocks.update(self.mock_context(item.context_expr, aliases))
                self.walk(statement.body, module, cls, inner, inner_mocks, emit)
                continue
            if isinstance(statement, ast.If):
                yes = self.walk(statement.body, module, cls, state, mocks, emit)
                no = self.walk(statement.orelse, module, cls, state, mocks, emit)
                state = yes and no
                continue
            if isinstance(statement, ast.Try):
                # A successful try body can continue; exceptional branches must
                # independently own any GUI they create.
                success = self.walk(statement.body, module, cls, state, mocks, emit)
                branches = [self.walk(h.body, module, cls, state, mocks, emit) for h in statement.handlers]
                state = success and all(branches) if branches else success
                state = self.walk(statement.orelse, module, cls, state, mocks, emit)
                state = self.walk(statement.finalbody, module, cls, state, mocks, emit)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                self.walk(statement.body, module, cls, state, mocks, emit)
                self.walk(statement.orelse, module, cls, state, mocks, emit)
                continue
            # Only a fixture installation on the unconditional path changes
            # ownership for later statements. An import/name mention does not.
            installs = self.fixture_install(statement, aliases)
            for call in (n for n in ast.walk(statement) if isinstance(n, ast.Call)):
                name = self.resolve(call.func, aliases)
                if name.startswith('self.') and cls:
                    name = self.method(cls, name[5:]) or name
                is_gui = self.is_gui(name)
                if name == 'tkinter.Tk' and (any(k.arg == 'useTk' and isinstance(k.value, ast.Constant) and k.value.value is False for k in call.keywords)
                                              or (len(call.args) > 3 and isinstance(call.args[3], ast.Constant) and call.args[3].value is False)):
                    is_gui = False
                mocked = name in mocks or (is_gui and not self.qt_mode and 'tkinter.Tk.__init__' in mocks)
                if is_gui and not mocked:
                    if emit:
                        self.entries.append(f'{relative}:{call.lineno}')
                    if not state and emit:
                        self.error(relative, call, 'GUI entry missing an earlier unconditional offscreen fixture')
                if name in self.required and not state and emit:
                    self.error(relative, call, f'{name} requires an active offscreen scope')
                # Native creation bypasses the constructor hooks. Do not accept
                # it merely because a Python scope happens to be active.
                if name == '_tkinter.create' or name.rsplit('.', 1)[-1] in ('CreateWindowExW', 'CreateWindowExA', 'CreateDialogParamW', 'CreateDialogParamA') or (name.endswith('.call') and call.args and
                        isinstance(call.args[0], ast.Constant) and call.args[0].value in ('toplevel', 'tk_messageBox', 'tk_getOpenFile', 'tk_getSaveFile')):
                    if emit:
                        self.error(relative, call, 'unadapted native GUI creation; use the managed Tk entry or mock the dialog')
            if installs:
                state = True
        return state

    def check_inline_children(self, module):
        relative, tree, aliases = self.modules[module]
        values = {}
        def literal(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return str(self.root / relative) if node.id == '__file__' else values.get(node.id)
            if isinstance(node, ast.Attribute) and node.attr == 'parent':
                value = literal(node.value)
                return str(Path(value).parent) if value is not None else None
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == 'parents':
                value = literal(node.value.value)
                if value is not None and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
                    return str(Path(value).parents[node.slice.value])
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                left, right = literal(node.left), literal(node.right)
                if right is not None:
                    return str(Path(left or '__dynamic_test_directory__') / right)
            if isinstance(node, ast.Call) and self.resolve(node.func, aliases) == 'textwrap.dedent' and node.args:
                value = literal(node.args[0])
                return textwrap.dedent(value) if value is not None else None
            if isinstance(node, ast.Call) and self.resolve(node.func, aliases) in ('str', 'pathlib.Path') and node.args:
                return literal(node.args[0])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                value = literal(node.func.value)
                if value is not None and node.func.attr == 'resolve':
                    return str(Path(value).resolve())
                if value is not None and node.func.attr == 'with_name' and node.args:
                    name = literal(node.args[0])
                    return str(Path(value).with_name(name)) if name else None
            return None

        def child_gui(child_tree):
            child_aliases = {}
            for item in ast.walk(child_tree):
                if isinstance(item, ast.Import):
                    for a in item.names:
                        child_aliases[a.asname or a.name.split('.')[0]] = a.name
                elif isinstance(item, ast.ImportFrom):
                    for a in item.names:
                        child_aliases[a.asname or a.name] = (item.module or '') + '.' + a.name
            gui = any(isinstance(n, ast.Call) and self.is_gui(self.resolve(n.func, child_aliases)) for n in ast.walk(child_tree))
            return gui, child_aliases

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = self.resolve(node.func, aliases)
            managed_child = name in ('tk_test_windows.run_gui_child', 'scripts.gui_test_process.run_gui_child')
            if name not in ('subprocess.run', 'subprocess.Popen') and not managed_child:
                continue
            # Bind constants only from this launch's module/function and only
            # before this launch. Same-named code strings in another test must
            # never overwrite a GUI child's source during preflight.
            owners = [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and f.lineno <= node.lineno <= f.end_lineno]
            scope = max(owners, key=lambda f: f.lineno) if owners else tree
            assignments = [n for n in tree.body if isinstance(n, ast.Assign)]
            assignments += [n for n in ast.walk(scope) if isinstance(n, ast.Assign) and n.lineno < node.lineno]
            values.clear()
            bindings = {}
            for assignment in sorted(assignments, key=lambda n: n.lineno):
                for target in assignment.targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = assignment.value
                        value = literal(assignment.value)
                        if value is not None:
                            values[target.id] = value
                        else:
                            values.pop(target.id, None)
            command = node.args[0]
            if isinstance(command, ast.Name):
                command = bindings.get(command.id, command)
            if not isinstance(command, (ast.List, ast.Tuple)):
                continue
            if not command.elts:
                continue
            first = literal(command.elts[0])
            python = self.resolve(command.elts[0], aliases) == 'sys.executable' or (
                first is not None and Path(first).name.lower() in ('python', 'python3', 'python.exe', 'python3.exe'))
            if python and not managed_child:
                # A unittest child may import GUI indirectly, so it must use
                # the evidence wrapper regardless of the selected test name.
                options = [a for a in command.elts[1:] if not (isinstance(a, ast.Constant) and
                           (str(a.value).startswith('-') or a.value == 'utf8'))]
                script = literal(options[0]) if options else None
                module_launch = any(isinstance(a, ast.Constant) and a.value == '-m' for a in command.elts) and not (script and script.endswith('.py'))
                if module_launch:
                    self.error(relative, node, 'Python module child must use run_gui_child for independent runtime evidence')
                has_inline = any(isinstance(a, ast.Constant) and a.value == '-c' for a in command.elts)
                if options and not has_inline and not module_launch:
                    code = None
                    if script and script.endswith('.py'):
                        path = Path(script)
                        if not path.is_absolute():
                            path = self.root / path
                        try:
                            path.resolve().relative_to(self.root.resolve())
                            if path.is_file():
                                code = path.read_text(encoding='utf-8-sig')
                        except ValueError:
                            pass
                    # Generated non-GUI process fixtures can be verified from
                    # their exact write_text source without a filename allowlist.
                    argument = options[0]
                    if isinstance(argument, ast.Call) and self.resolve(argument.func, aliases) == 'str' and argument.args:
                        argument = argument.args[0]
                    if code is None:
                        for write in ast.walk(scope):
                            if isinstance(write, ast.Call) and isinstance(write.func, ast.Attribute) and write.func.attr == 'write_text' and write.args:
                                if ast.dump(write.func.value) == ast.dump(argument):
                                    code = literal(write.args[0])
                    trusted_wrapper = script and Path(script).resolve() == (self.root / 'scripts/run_gui_child.py').resolve()
                    if not trusted_wrapper:
                        if code is None:
                            self.error(relative, node, 'unresolved Python script child; use run_gui_child or an inspectable script')
                        else:
                            try:
                                gui, _ = child_gui(ast.parse(code))
                            except SyntaxError:
                                self.error(relative, node, 'cannot parse child script')
                            else:
                                if gui:
                                    self.error(relative, node, 'GUI script child must use run_gui_child for independent runtime evidence')
            for index, arg in enumerate(command.elts[:-1]):
                if not isinstance(arg, ast.Constant) or arg.value != '-c':
                    continue
                code = literal(command.elts[index + 1])
                if code is None:
                    self.error(relative, node, 'unresolved inline Python child; use an inspectable child script')
                    continue
                try:
                    child_tree = ast.parse(code)
                except SyntaxError:
                    self.error(relative, node, 'cannot parse inline child')
                    continue
                # Inspect the inline program with its own imports/scopes, not
                # with the parent's fixture or aliases.
                child_module = module + '.__child_' + str(node.lineno)
                gui, child_aliases = child_gui(child_tree)
                if gui:
                    if not managed_child:
                        self.error(relative, node, 'GUI child must use run_gui_child for independent runtime evidence')
                    self.modules[child_module] = (relative + f':child@{node.lineno}', child_tree, child_aliases)
                    self.walk(child_tree.body, child_module)

    def check(self):
        self.load()
        for name, (node, module, cls) in self.functions.items():
            if any(self.resolve(d, self.modules[module][2]) == self.scope_decorator for d in node.decorator_list):
                self.required.add(name)
        # Fixed point allows derived test classes to inherit the protected setup.
        for cls in self.classes:
            setup = self.method(cls, 'setUp')
            if setup:
                node, module, _owner = self.functions[setup]
                if self.walk(node.body, module, cls, emit=False):
                    self.installed_classes.add(cls)
        for module, (relative, tree, aliases) in list(self.modules.items()):
            if not relative.startswith('tests/') or relative == 'tests/tk_test_windows.py':
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(a.name.split('.')[0] in ('PyQt5', 'PyQt6', 'PySide2', 'wx') for a in node.names):
                    self.error(relative, node, 'GUI framework has no offscreen test adapter')
                if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in ('PyQt5', 'PyQt6', 'PySide2', 'wx'):
                    self.error(relative, node, 'GUI framework has no offscreen test adapter')
                is_qt_import = ((isinstance(node, ast.Import) and any(a.name.split('.')[0] == 'PySide6' for a in node.names))
                                or (isinstance(node, ast.ImportFrom) and (node.module or '').startswith('PySide6')))
                if self.qt_mode and is_qt_import and not any(
                    isinstance(call, ast.Call) and (self.scope_context(call, aliases) or
                    self.resolve(call.func, aliases) == 'qt_test_guard.install_qt_test_scope')
                    for call in ast.walk(tree)):
                    self.error(relative, node, 'Qt framework import requires an explicit Qt ownership fixture')
            self.walk(tree.body, module)
            self.check_inline_children(module)
        for name, (node, module, cls) in self.functions.items():
            relative = self.modules[module][0]
            if not relative.startswith('tests/') or relative == 'tests/tk_test_windows.py':
                continue
            protected = name in self.required or (cls in self.installed_classes and node.name != 'setUp')
            self.walk(node.body, module, cls, protected)
        return sorted(set(self.errors))


class QtCoverage(Coverage):
    qt_mode = True
    scope_decorator = 'qt_test_guard.requires_qt_scope'

    def __init__(self, root):
        super().__init__(root)
        self.gui_classes = {'PySide6.QtWidgets.' + name for name in (
            'QApplication', 'QWidget', 'QMainWindow', 'QDialog', 'QFrame',
            'QScrollArea', 'QTableView', 'QListView', 'QTreeView')}

    def is_gui(self, name):
        return name in self.gui_classes or (name.startswith('PySide6.QtWidgets.Q') and name.count('.') == 2)

    def fixture_install(self, statement, aliases):
        call = statement.value if isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign)) else None
        return isinstance(call, ast.Call) and self.resolve(call.func, aliases) == 'qt_test_guard.install_qt_test_scope'

    def scope_context(self, node, aliases):
        return isinstance(node, ast.Call) and self.resolve(node.func, aliases) == 'qt_test_guard.QtTestScope'


def check(root):
    return sorted(set(Coverage(root).check() + QtCoverage(root).check()))


def main():
    coverage = Coverage(Path(__file__).resolve().parents[1])
    qt_coverage = QtCoverage(Path(__file__).resolve().parents[1])
    errors = sorted(set(coverage.check() + qt_coverage.check()))
    for error in errors:
        print(error)
    if errors:
        print(f'GUI_TEST_COVERAGE_FAILED: {len(errors)} issue(s)')
        return 1
    print(f'GUI_TEST_COVERAGE_OK: {len(set(coverage.entries + qt_coverage.entries))} GUI construction sites reviewed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
