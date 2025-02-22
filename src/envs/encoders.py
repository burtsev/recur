# Copyright (c) 2015-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the CC-by-NC license found in the
# LICENSE file in the root directory of this source tree.
#

from abc import ABC, abstractmethod
import numpy as np
import math
from .generators import all_operators, math_constants, Node, NodeList

class Encoder(ABC):
    """
    Base class for encoders, encodes and decodes matrices
    abstract methods for encoding/decoding numbers
    """
    def __init__(self, params):
        pass

    @abstractmethod
    def encode(self, val):
        pass

    @abstractmethod
    def decode(self, lst):
        pass

class IntegerSequences(Encoder):
    def __init__(self, params):
        super().__init__(params)
        self.int_base = params.int_base
        self.symbols = ['+', '-', ',']
        self.symbols.extend([str(i) for i in range(self.int_base)])

    def encode(self, value):
        seq = []
        for val in value:
            seq.append('+' if val >= 0 else '-')
            vseq = []
            w = abs(val)
            if w == 0:
                seq.append('0')
            else:
                while w > 0:
                    vseq.append(str(w % self.int_base))
                    w = w // self.int_base
                seq.extend(vseq[::-1])
        return seq

    def decode(self, lst):
        
        if len(lst) == 0:
            return None
        res = []
        if lst[0] in ["+", "-"]:
            curr_group = [lst[0]]
        else:
            return None
        if lst[-1] in ["+", "-"]:
            return None

        for x in lst[1:]:
            if x in ["+", "-"]:
                if len(curr_group)>1:
                    sign = 1 if curr_group[0]=="+" else -1
                    value = 0
                    for elem in curr_group[1:]:
                        value = value*self.int_base + int(elem)
                    res.append(sign*value)
                    curr_group = [x]
                else:
                    return None
            else:
                curr_group.append(x)
        if len(curr_group)>1:
            sign = 1 if curr_group[0]=="+" else -1
            value = 0
            for elem in curr_group[1:]:
                value = value*self.int_base + int(elem)
            res.append(sign*value)
        return res
    
class FloatSequences(Encoder):
    def __init__(self, params):
        super().__init__(params)
        self.float_precision = params.float_precision
        self.mantissa_len = params.mantissa_len
        self.max_exponent = params.max_exponent
        self.base = (self.float_precision+1)//self.mantissa_len
        self.max_token = 10 ** self.base
        self.symbols = ['+','-']
        self.symbols.extend(['N' + f"%0{self.base}d" % i for i in range(self.max_token)])
        self.symbols.extend(['E' + str(i) for i in range(-self.max_exponent, self.max_exponent+1)])

    def encode(self, value):
        """
        Write a float number
        """
        seq = []
        precision = self.float_precision
        for val in value:
            assert val not in [-np.inf, np.inf]
            sign = '+' if val>=0 else '-'
            m, e = (f"%.{precision}e" % val).split("e")
            i, f = m.lstrip("-").split(".")
            i = i + f
            tokens = self.chunks(i, (precision+1)//self.mantissa_len)
            expon = int(e) - precision
            if expon < -self.max_exponent:
                tokens = ['0'*self.base]*self.mantissa_len
                expon = int(0)
            seq.extend([sign, *['N' + token for token in tokens], "E" + str(expon)])
        return seq
    
    def chunks(self, lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def decode(self, lst):
        """
        Parse a list that starts with a float.
        Return the float value, and the position it ends in the list.
    """
        if len(lst)==0:
            return None
        seq = []
        for val in self.chunks(lst, 2+self.mantissa_len):
            for x in val: 
                if x[0] not in ['-','+','E','N']: return np.nan
            try:
                sign = 1 if val[0]=='+' else -1
                mant = ''
                for x in val[1:-1]:
                    mant += x[1:]
                mant = int(mant)
                exp = int(val[-1][1:])
                value = sign * mant * (10 ** exp)
                value=float(value)
            except Exception:
                value = np.nan
            seq.append(value)
        return seq
    
class Equation(Encoder):
    def __init__(self, params, symbols):
        super().__init__(params)
        self.params = params
        self.max_int = self.params.max_int
        self.symbols = symbols
        if params.extra_unary_operators!="":
            self.extra_unary_operators=self.params.extra_unary_operators.split(",")
        else:
            self.extra_unary_operators=[]
        if params.extra_binary_operators!="":
            self.extra_binary_operators=self.params.extra_binary_operators.split(",")
        else:
            self.extra_binary_operators=[]

    def encode(self, tree):
        res = []
        for elem in tree.prefix().split(','):
            try:
                val=float(elem) 
                if (val).is_integer():
                    res.extend(self.write_int(int(elem)))
                else:
                    res.append("OOD_constant")
            except ValueError:
                res.append(elem)
        return res

    def _decode(self, lst):
        if len(lst)==0:
            return None, 0
        if (lst[0] not in self.symbols) and (not lst[0].lstrip('-').isdigit()):
            return None, 0
        if "OOD" in lst[0]:
            return None, 0
        if lst[0] in all_operators.keys():
            res = Node(lst[0], self.params)
            arity = all_operators[lst[0]]
            pos = 1
            for i in range(arity):
                child, length = self._decode(lst[pos:])
                if child is None:
                    return None, pos
                res.push_child(child)
                pos += length
            return res, pos
        elif lst[0].startswith('INT'):
            val, length = self.parse_int(lst)
            return Node(str(val), self.params), length
        else: # other leafs
            return Node(lst[0], self.params), 1

    
    def decode(self, lst):
        trees = []
        lists = self.split_at_value(lst, '|')
        for lst in lists:
            tree = self._decode(lst)[0]
            if tree is None: return None
            trees.append(tree)
        tree = NodeList(trees)
        return tree
    
    def split_at_value(self, lst, value):
        indices = [i for i, x in enumerate(lst) if x==value]
        res = []
        for start, end in zip([0, *[i+1 for i in indices]], [*[i-1 for i in indices], len(lst)]):
            res.append(lst[start:end+1])
        return res
    
    def parse_int(self, lst):
        """
        Parse a list that starts with an integer.
        Return the integer value, and the position it ends in the list.
        """
        base = self.max_int
        val = 0
        i = 0
        for x in lst[1:]:
            if not (x.rstrip('-').isdigit()):
                break
            val = val * base + int(x)
            i += 1
        if base > 0 and lst[0] == 'INT-':
            val = -val
        return val, i + 1

    def write_int(self, val):
        """
        Convert a decimal integer to a representation in the given base.
        """
        base = self.max_int
        res = []
        max_digit = abs(base)
        neg = val < 0
        val = -val if neg else val
        while True:
            rem = val % base
            val = val // base
            if rem < 0 or rem > max_digit:
                rem -= base
                val += 1
            res.append(str(rem))
            if val == 0:
                break
        res.append('INT-' if neg else 'INT+')
        return res[::-1]
            
