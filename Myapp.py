#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小学四则运算题目自动生成与判分程序

用法举例：
生成题目（必须指定 -r）：
    python Myapp.py -r 10 -n 20

判分（给定题目文件与答案文件）：
    python Myapp.py -e Exercises.txt -a Answers.txt

说明：
- 题目输出到 Exercises.txt（当前目录），每行一个题目，格式类似： "1 + 2/3 × (3 - 1) ="
- 答案输出到 Answers.txt，对应每题一行，分数以带分数形式输出（例如 2'1/3）或整数或真分数 a/b。
- Grade.txt 为判分输出。
"""
import argparse
import random
import math
from fractions import Fraction
import sys
import re
from typing import Optional, Tuple, List, Union, Set

# ---------------------------
# 表示表达式的树结构
# ---------------------------
class Expr:
    # either value (Fraction) with .value != None and op is None
    # or op node with op in '+-*/' and left/right Expr
    def __init__(self, value: Optional[Fraction] = None, op: Optional[str] = None, left=None, right=None):
        self.value = value
        self.op = op
        self.left: Optional[Expr] = left
        self.right: Optional[Expr] = right

    def is_leaf(self):
        return self.op is None

    def eval(self) -> Fraction:
        if self.is_leaf():
            return self.value
        a = self.left.eval()
        b = self.right.eval()
        if self.op == '+':
            return a + b
        if self.op == '-':
            return a - b
        if self.op == '*':
            return a * b
        if self.op == '/':
            # division by zero should not occur
            return a / b
        raise ValueError("Unknown op")

    # produce human-readable expression string with spacing around operators and = at end if desired
    def to_string(self) -> str:
        if self.is_leaf():
            return format_fraction_display(self.value)
        left = self.left.to_string()
        right = self.right.to_string()
        return f"{wrap_if_needed(self.left)} {self.op} {wrap_if_needed(self.right)}"

    # canonical string used for deduplication: for commutative ops + and * we flatten and sort operand canonical forms
    def canonical(self) -> str:
        if self.is_leaf():
            # canonical representation of a value: reduced fraction string numerator/denominator or integer
            return canonical_number_str(self.value)
        if self.op in ('+', '*'):
            # flatten operands with same op
            terms = self._collect_flat(self.op)
            # get canonical of each term
            terms_canon = [t.canonical() for t in terms]
            terms_canon.sort()
            return f"({self.op.join(terms_canon)})"
        else:
            return f"({self.left.canonical()}{self.op}{self.right.canonical()})"

    def _collect_flat(self, op):
        # returns list of Expr that are flattened under given op
        res = []
        def dfs(e):
            if not e.is_leaf() and e.op == op:
                dfs(e.left)
                dfs(e.right)
            else:
                res.append(e)
        dfs(self)
        return res

# ---------------------------
# 格式化与解析分数/带分数
# ---------------------------

def format_fraction_display(fr: Fraction) -> str:
    # simplify
    fr = fr  # Fraction already reduced
    if fr.denominator == 1:
        return str(fr.numerator)
    num = abs(fr.numerator)
    den = fr.denominator
    if num > den:
        # mixed number: m'n/d
        m = num // den
        r = num % den
        sign = '-' if fr.numerator < 0 else ''
        return f"{sign}{m}'{r}/{den}"
    else:
        sign = '-' if fr.numerator < 0 else ''
        return f"{sign}{num}/{den}"

def canonical_number_str(fr: Fraction) -> str:
    # canonical stable representation for dedup (no mixed form)
    fr = Fraction(fr.numerator, fr.denominator)  # normalized
    return f"{fr.numerator}/{fr.denominator}" if fr.denominator != 1 else f"{fr.numerator}/1"

# ---------------------------
# 帮助函数：当子表达式为非叶子且需要加入括号时加括号
# ---------------------------
def wrap_if_needed(node: Expr) -> str:
    # operator precedence
    if node.is_leaf():
        return format_fraction_display(node.value)
    # precedence mapping
    prec = {'+':1, '-':1, '*':2, '/':2}
    # if child op has lower precedence than parent when printed in parent, we need parentheses;
    # but since we don't know parent here, we'll follow a simple rule: always wrap child if child is op and either:
    # - child is op and parent op is different and parent's precedence > child's? To be safe, always add parentheses around non-leaf except when leaf.
    # However to match examples and readability, we add parentheses when child is not leaf and has operator.
    return f"({node.to_string()})"

# ---------------------------
# 解析生成/检查表达式的约束
# ---------------------------

def non_negative(fr: Fraction) -> bool:
    return fr >= 0

def is_division_result_fraction(a: Fraction, b: Fraction) -> bool:
    # division result must be non-integer rational number (i.e., a / b not integer)
    if b == 0:
        return False
    res = a / b
    return res.denominator != 1  # not integer

# ---------------------------
# 生成随机叶子（自然数或真分数）
# leaf values constrained by range r (natural numbers < r for natural part and denominator)
# 真分数这里我们允许任意 Fraction with numerator and denominator in range, numerator>0
# ---------------------------
def random_leaf(r: int) -> Fraction:
    # choose between integer and fraction with some bias
    # ensure natural numbers range is [0, r-1]
    if r <= 1:
        # only 0 allowed? but r must be >=1 per spec; handle anyway
        return Fraction(0,1)
    if random.random() < 0.5:
        # integer
        return Fraction(random.randint(0, r-1), 1)
    else:
        # create fraction: choose denominator in [2, r] (excluding 1), numerator in [1, denom*(r-1)]? but we want reasonable magnitude
        denom = random.randint(2, max(2, r))
        # numerator up to denom*(r-1) to allow mixed numbers; but keep numerator small to avoid huge mixes
        # we'll decide whether to create proper fraction or mixed sometimes
        if random.random() < 0.6:
            # proper fraction < r
            num = random.randint(1, denom - 1)
            return Fraction(num, denom)
        else:
            # mixed-like fraction >1
            whole = random.randint(1, max(1, r-1))
            num = random.randint(1, denom - 1)
            return Fraction(whole * denom + num, denom)

# ---------------------------
# 随机构造表达式树（确保约束）
# 算符数 op_count (1~3)
# 采用生成并回溯尝试的策略：生成子树、若约束不满足则重试（带尝试次数上限）
# ---------------------------
OPS = ['+', '-', '*', '/']

def generate_expression(op_count: int, r: int, max_tries: int = 200) -> Optional[Expr]:
    # we'll attempt repeated random constructions until constraints satisfied
    for attempt in range(max_tries):
        # generate a random binary tree shape with op_count operators: will create op_count internal nodes, leaves = op_count+1
        leaves_vals = [random_leaf(r) for _ in range(op_count + 1)]
        # create initial list of Expr leaves
        leaf_nodes = [Expr(value=v) for v in leaves_vals]
        # randomly combine adjacent nodes to form binary tree until single node
        nodes = leaf_nodes[:]
        ops_choices = []
        # to attempt produce various shapes, we randomly pick adjacent pair and operator
        valid = True
        # We need to choose operators sequence too
        # We'll construct left-to-right combining random neighbors
        for _ in range(op_count):
            # pick index i for combining nodes[i] and nodes[i+1]
            if len(nodes) < 2:
                valid = False
                break
            i = random.randint(0, len(nodes) - 2)
            left = nodes[i]
            right = nodes[i+1]
            op = random.choice(OPS)
            new_node = Expr(op=op, left=left, right=right)
            # evaluate safety constraints locally: no negative intermediate, division result not integer
            try:
                aval = left.eval()
                bval = right.eval()
            except Exception:
                valid = False
                break
            # For subtraction ensure aval >= bval
            if op == '-':
                if not (aval >= bval):
                    valid = False
                    break
                res = aval - bval
            elif op == '/':
                if bval == 0:
                    valid = False
                    break
                # division result must be fractional (non-integer)
                if not is_division_result_fraction(aval, bval):
                    valid = False
                    break
                res = aval / bval
            elif op == '+':
                res = aval + bval
            elif op == '*':
                res = aval * bval
            else:
                valid = False
                break
            # ensure result non-negative
            if not non_negative(res):
                valid = False
                break
            # replace nodes[i:i+2] with new_node
            nodes[i:i+2] = [new_node]
        if not valid:
            continue
        if len(nodes) != 1:
            continue
        root = nodes[0]
        # final checks: evaluate tree to ensure no negative anywhere (already checked local), and operators count correct
        # also ensure intermediate subtractions in nested nodes satisfied: we checked locally at combine time so okay
        return root
    return None

# ---------------------------
# 去重判定：canonical 表示
# ---------------------------
def format_expression_for_output(expr: Expr) -> str:
    s = expr.to_string()
    # ensure single space around operators and final ' ='
    return f"{s} ="

# ---------------------------
# 生成 N 道题目（无重复）
# ---------------------------
def generate_problems(n: int, r: int) -> List[Tuple[str, str]]:
    # returns list of tuples (expr_str, answer_str)
    seen: Set[str] = set()
    problems = []
    tries = 0
    max_total_tries = max(10000, n * 200)
    while len(problems) < n and tries < max_total_tries:
        tries += 1
        op_count = random.randint(1, 3)  # op count between 1 and 3
        expr = generate_expression(op_count, r)
        if expr is None:
            continue
        canon = expr.canonical()
        if canon in seen:
            continue
        # also ensure uniqueness up to commutativity we've canonicalized
        seen.add(canon)
        expr_str = format_expression_for_output(expr)
        ans_frac = expr.eval()
        ans_str = format_fraction_display(ans_frac)
        problems.append((expr_str, ans_str))
    if len(problems) < n:
        raise RuntimeError(f"无法在给定尝试次数内生成足够题目（要求 {n}, 实际 {len(problems)}）。请增大 r 或放宽限制。")
    return problems

# ---------------------------
# 解析表达式（用于判分）- 支持 a, a/b, m'n/d 格式
# 使用 Shunting-yard 转换为 RPN，然后计算为 Fraction
# ---------------------------
token_re = re.compile(r"\s*(\d+'[0-9]+/[0-9]+|\d+/\d+|\d+|[()+\-*/])\s*")

def tokenize(expr: str) -> List[str]:
    tokens = token_re.findall(expr)
    # token_re will only capture valid tokens; but inputs may contain '=' at end - strip it earlier
    return tokens

def parse_number_token(tok: str) -> Fraction:
    # mixed number m'n/d
    if "'" in tok:
        parts = tok.split("'")
        whole = int(parts[0])
        frac_part = parts[1]
        num, den = map(int, frac_part.split('/'))
        return Fraction(whole * den + num, den)
    if "/" in tok:
        num, den = map(int, tok.split('/'))
        return Fraction(num, den)
    return Fraction(int(tok), 1)

def shunting_yard(tokens: List[str]) -> List[Union[str, Fraction]]:
    # return RPN list where numbers are Fraction objects, operators are strings
    out = []
    ops_stack = []
    prec = {'+':1, '-':1, '*':2, '/':2}
    for tok in tokens:
        if re.fullmatch(r"\d+'[0-9]+/[0-9]+|\d+/\d+|\d+", tok):
            out.append(parse_number_token(tok))
        elif tok in ('+', '-', '*', '/'):
            while ops_stack and ops_stack[-1] != '(' and prec.get(ops_stack[-1],0) >= prec[tok]:
                out.append(ops_stack.pop())
            ops_stack.append(tok)
        elif tok == '(':
            ops_stack.append(tok)
        elif tok == ')':
            while ops_stack and ops_stack[-1] != '(':
                out.append(ops_stack.pop())
            if not ops_stack:
                raise ValueError("Mismatched parentheses")
            ops_stack.pop()  # pop '('
        else:
            raise ValueError(f"Unknown token: {tok}")
    while ops_stack:
        op = ops_stack.pop()
        if op in ('(', ')'):
            raise ValueError("Mismatched parentheses")
        out.append(op)
    return out

def eval_rpn(rpn: List[Union[str, Fraction]]) -> Fraction:
    stack: List[Fraction] = []
    for item in rpn:
        if isinstance(item, Fraction):
            stack.append(item)
        else:
            if len(stack) < 2:
                raise ValueError("Invalid RPN")
            b = stack.pop()
            a = stack.pop()
            if item == '+':
                stack.append(a + b)
            elif item == '-':
                stack.append(a - b)
            elif item == '*':
                stack.append(a * b)
            elif item == '/':
                if b == 0:
                    raise ZeroDivisionError
                stack.append(a / b)
            else:
                raise ValueError("Unknown op")
    if len(stack) != 1:
        raise ValueError("Invalid RPN final")
    return stack[0]

def evaluate_expression_str(expr_line: str) -> Fraction:
    # strip trailing '=' and spaces
    expr_line = expr_line.strip()
    if expr_line.endswith('='):
        expr_line = expr_line[:-1].strip()
    tokens = tokenize(expr_line)
    if not tokens:
        raise ValueError("No tokens")
    rpn = shunting_yard(tokens)
    return eval_rpn(rpn)

# ---------------------------
# 文件输出：Exercises.txt, Answers.txt
# ---------------------------
def write_exercises_answers(problems: List[Tuple[str,str]], exercises_file: str = "Exercises.txt", answers_file: str = "Answers.txt"):
    with open(exercises_file, 'w', encoding='utf-8') as fe:
        for expr, _ in problems:
            fe.write(expr + "\n")
    with open(answers_file, 'w', encoding='utf-8') as fa:
        for _, ans in problems:
            fa.write(ans + "\n")

# ---------------------------
# 判分功能
# ---------------------------
def grade(exercise_file: str, answer_file: str, grade_file: str = "Grade.txt"):
    # read exercises
    with open(exercise_file, 'r', encoding='utf-8') as f:
        ex_lines = [line.rstrip('\n') for line in f if line.strip() != ""]
    with open(answer_file, 'r', encoding='utf-8') as f:
        ans_lines = [line.rstrip('\n') for line in f if line.strip() != ""]
    n = len(ex_lines)
    # allow answers file to have >= n lines; only compare first n
    m = min(n, len(ans_lines))
    correct_idx = []
    wrong_idx = []
    for i in range(n):
        try:
            ex = ex_lines[i]
            # compute true answer
            true_ans = evaluate_expression_str(ex)
        except Exception as e:
            # if exercise can't be parsed, mark wrong
            true_ans = None
        if i >= len(ans_lines):
            wrong_idx.append(i+1)
            continue
        provided = ans_lines[i].strip()
        # parse provided answer to Fraction
        try:
            prov_frac = parse_answer_token(provided)
        except Exception:
            wrong_idx.append(i+1)
            continue
        if true_ans is None:
            wrong_idx.append(i+1)
        else:
            if prov_frac == true_ans:
                correct_idx.append(i+1)
            else:
                wrong_idx.append(i+1)
    # produce Grade.txt
    with open(grade_file, 'w', encoding='utf-8') as fg:
        fg.write(f"Correct: {len(correct_idx)}")
        if correct_idx:
            fg.write(" (" + ", ".join(map(str, correct_idx)) + ")")
        fg.write("\n\n")
        fg.write(f"Wrong: {len(wrong_idx)}")
        if wrong_idx:
            fg.write(" (" + ", ".join(map(str, wrong_idx)) + ")")
        fg.write("\n")
    print(f"Grading done. Correct: {len(correct_idx)}, Wrong: {len(wrong_idx)}. See {grade_file}")

def parse_answer_token(s: str) -> Fraction:
    s = s.strip()
    if s == "":
        raise ValueError("Empty")
    # support mixed m'n/d, fraction a/b, integer
    if re.fullmatch(r"-?\d+'[0-9]+/[0-9]+", s):
        sign = -1 if s.startswith('-') else 1
        if s.startswith('-'):
            s2 = s[1:]
        else:
            s2 = s
        parts = s2.split("'")
        whole = int(parts[0])
        num, den = map(int, parts[1].split('/'))
        return Fraction(sign * (whole * den + num), den)
    if re.fullmatch(r"-?\d+/\d+", s):
        num, den = map(int, s.split('/'))
        return Fraction(num, den)
    if re.fullmatch(r"-?\d+", s):
        return Fraction(int(s), 1)
    # try to accept something like 2 1/3 or 2'1/3 with space
    m = re.fullmatch(r"(-?\d+)\s+(\d+)/(\d+)", s)
    if m:
        whole = int(m.group(1))
        num = int(m.group(2))
        den = int(m.group(3))
        sign = -1 if whole < 0 else 1
        whole = abs(whole)
        return Fraction(sign * (whole * den + num), den)
    raise ValueError("Can't parse answer token")

# ---------------------------
# CLI 主入口
# ---------------------------
def main():
    parser = argparse.ArgumentParser(description="四则运算题目生成与判分工具")
    group = parser.add_mutually_exclusive_group(required=False)
    parser.add_argument("-r", type=int, help="数值范围 r（必须给定用于生成模式，表示上限，不含 r）")
    parser.add_argument("-n", type=int, default=10, help="生成题目数量（默认10）")
    parser.add_argument("-e", type=str, help="题目文件 Exercises.txt（用于判分模式）")
    parser.add_argument("-a", type=str, help="答案文件 Answers.txt（用于判分模式）")
    args = parser.parse_args()

    # 判分模式（如果 -e 和 -a 都给出）
    if args.e or args.a:
        if not args.e or not args.a:
            print("判分模式需要同时指定 -e <exercisefile> -a <answerfile>")
            sys.exit(1)
        grade(args.e, args.a)
        return

    # 生成模式：必须给 -r
    if args.r is None:
        parser.print_help()
        print("\n生成模式需要指定 -r 参数（例如 -r 10 表示数值范围为 0..9）")
        sys.exit(1)
    r = args.r
    if r <= 0:
        print("参数 -r 必须是自然数（>=1）")
        sys.exit(1)
    n = args.n
    if n <= 0:
        print("参数 -n 必须为正整数")
        sys.exit(1)
    if n > 10000:
        print("单次生成题数上限为10000，请分批生成")
        sys.exit(1)

    # set random seed for unpredictability; user can adjust if deterministic needed
    random.seed()

    try:
        problems = generate_problems(n, r)
    except Exception as e:
        print("生成题目失败：", e)
        sys.exit(1)

    write_exercises_answers(problems, "Exercises.txt", "Answers.txt")
    print(f"生成完成：Exercises.txt 与 Answers.txt 已写入当前目录，共 {n} 道题。")

if __name__ == "__main__":
    main()
