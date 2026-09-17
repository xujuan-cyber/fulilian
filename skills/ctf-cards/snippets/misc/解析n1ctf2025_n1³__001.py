# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/解析n1ctf2025_(n1)³.md
# TITLE: 解析n1ctf2025 (n1)³
# CATEGORY: misc

FLAG = ZZ.from_bytes(os.getenvb(b"FLAG",b"n1ctf{.*}")[6:-1]).digits(257)F, n = GF(257), len(FLAG)U, T = [random_matrix(F, n)for_in':)']enc =lambdax: (x * U).apply_map(lambdac: c^3) * Tprint(enc(vector(F[",".join(f"x{i}"foriinrange(n))].gens())))print(enc(vector(F, FLAG)))
enc(x) = (x * U).apply_map(lambda c: c^3) * T
f(x) = ((xU)^{[3]})T
f(x) = Σ(k=1 to 35) wₖ ⋅ (vₖᵀx)³
S[i,j,k] = Σ(m=1 to 35) wₘ[i] ⋅ vₘ[j] ⋅ vₘ[k] ⋅ vₘ[l]
f(x) = Σ(k=1 to 35) wₖ ⋅ (vₖᵀx)³
A = S^(c) ×₃ a, B = S^(c) ×₃ b
X = A B^(-1)
defparse_polynomials(poly_line): poly_system = poly_line[1:-1] # 去掉外层括号 polynomials = [] current_poly ="" paren_count =0 forcharinpoly_system: current_poly += char ifchar =='(': paren_count +=1 elifchar ==')': paren_count -=1 elifchar ==','andparen_count ==0: # 找到多项式分隔符 polynomials.append(current_poly[:-1].strip()) current_poly =""
fᵢ(x) = Σ(j,k,l) S[i,j,k,l] ⋅ xⱼ ⋅ xₖ ⋅ xₗ
defmultiplicity_of_tuple(tup): cnt = Counter(tup) mult = math.factorial(3) forvincnt.values(): mult //= math.factorial(v) returnmult
# 对称化sorted_idxs = tuple(sorted(idxs))mult = multiplicity_of_tuple(sorted_idxs)inv_mult = pow(mult,-1, MOD)S_list[m][sorted_idxs] = (S_list[m].get(sorted_idxs,0) + coeff * inv_mult) % MOD
defmat_inv(M): N = len(M) # 构造增广矩阵 [M|I] mat = [row + [1ifi==jelse0forjinrange(N)]fori,rowinenumerate(M)] # 高斯消元 forcolinrange(N): # 选择主元 pivot_row =None forrinrange(col, N): ifmat[r][col] % MOD !=0: pivot_row = r break ifpivot_rowisNone: returnNone
# 矩阵奇异 # 交换行 ifpivot_row != col: mat[col], mat[pivot_row] = mat[pivot_row], mat[col] # 归一化主元 inv_pivot = pow(mat[col][col],-1, MOD) mat[col] = [(val * inv_pivot) % MODforvalinmat[col]] # 消元 forrinrange(N): ifr != col: factor = mat[r][col] iffactor !=0: mat[r] = [(mat[r][c] - factor * mat[col][c]) % MODforcinrange(2*N)] # 提取逆矩阵 return[row[N:]forrowinmat]
defdet_mod(M): N = len(M) mat = [row[:]forrowinM] det =1 foriinrange(N): # 寻找主元 pivot =None forrinrange(i, N): ifmat[r][i] % MOD !=0: pivot = r break ifpivotisNone: return0 ifpivot != i: mat[i], mat[pivot] = mat[pivot], mat[i] det = (-det) % MOD det = (det * mat[i][i]) % MOD inv_pivot = pow(mat[i][i],-1, MOD) # 消元 forrinrange(i+1, N): ifmat[r][i] !=0: factor = (mat[r][i] * inv_pivot) % MOD forcinrange(i, N): mat[r][c] = (mat[r][c] - factor * mat[i][c]) % MOD returndet % MOD
defbuild_Sc(c): """用随机向量c对张量进行线性收缩""" Sc = {} form_val, Sminenumerate(S_list): cm = c[m_val] % MOD ifcm ==0: continue foridxs, valinSm.items(): Sc[idxs] = (Sc.get(idxs,0) + cm * val) % MOD returnScdefbuild_contract_matrices_from_Sc(Sc, a, b): """构造收缩矩阵A和B""" A = [[0]*nfor_inrange(n)] B = [[0]*nfor_inrange(n)] for(i,j,k), valinSc.items(): # 考虑所有排列 perms = set(itertools.permutations((i,j,k))) for(p,q,r)inperms: A[p][q] = (A[p][q] + val * a[r]) % MOD B[p][q] = (B[p][q] + val * b[r]) % MOD returnA, B
# 计算X = A * B^(-1)Binv = mat_inv(B)ifBinvisNone: continue
# B不可逆，跳过X = mat_mul(A, Binv)
# 寻找特征值eigenvals = []fortinrange(MOD): M = [[(X[i][j] - (tifi==jelse0)) % MODforjinrange(n)]foriinrange(n)] ifdet_mod(M) ==0: eigenvals.append(t)
# 计算特征向量eigvecs = []forlamineigenvals: M = [[(X[i][j] - (lamifi==jelse0)) % MODforjinrange(n)]foriinrange(n)] basis = nullspace_mod(M) forvinbasis: # 归一化 foridx, valinenumerate(v): ifval !=0: inv = pow(val,-1, MOD) v = [(x * inv) % MODforxinv] break eigvecs.append(v)
# 构造V矩阵V = [[eigvecs[col][row]forcolinrange(n)]forrowinrange(n)]# V的三次方V_cubed = [[pow(V[j][k],3, MOD)forkinrange(n)]forjinrange(n)]# 求解WVc_inv = mat_inv(V_cubed)W = mat_mul(Vc_inv, A_rows)
defeval_poly(x): """直接计算多项式值""" res = [0]*n form_idxinrange(n): s =0 forcoeff, idxsinmonos_all[m_idx]: iflen(idxs) ==0: s = (s + coeff) % MOD else: term = coeff foridxinidxs: term = (term * x[idx]) % MOD s = (s + term) % MOD res[m_idx] = s returnres
# 验证分解是否正确for_inrange(3): x_test = [random.randrange(MOD)for_inrange(n)] u = [sum(V[row][k] * x_test[row]forrowinrange(n)) % MODforkinrange(n)] y_from = [sum(W[k][m] * pow(u[k],3, MOD)forkinrange(n)) % MODforminrange(n)] y_true = eval_poly(x_test) ify_from != y_true: ok =False break
A_rows = V^∘³ W
y = Σ(k) wₖ uₖ³, 其中 uₖ = (vₖᵀ x)
y = Wᵀ u^∘³
u^∘³ = (Wᵀ)^(-1) y
u = (u^∘³)^(3^(-1) mod 256) （逐坐标幂）
Vᵀ x = u
# 1. 解u^3WT = [[found_W[i][j]foriinrange(n)]forjinrange(n)]WT_inv = mat_inv(WT)u3 = [sum(WT_inv[i][j] * y[j]forjinrange(n)) % MODforiinrange(n)]# 2. 计算三次方根（在GF(257)中唯一）inv3 = pow(3,-1, MOD-1) # 3在模256下的逆元u = [pow(val, inv3, MOD)forvalinu3]# 3. 解xVt = [[found_V[row][col]forrowinrange(n)]forcolinrange(n)]Vt_inv = mat_inv(Vt)x_sol = [sum(Vt_inv[i][j] * u[j]forjinrange(n)) % MODforiinrange(n)]
# 重构整数（LSB在前）value =0fori, dinenumerate(x_sol): value += d * pow(257, i)
# 转换为字节blen = (value.bit_length() +7) //8flag_bytes = value.to_bytes(blen,'big')
# 检查矩阵是否可逆ifmat_inv(B)isNone: continue
# 跳过不可逆情况
# 将特征向量归一化，使第一个非零元素为1foridx, valinenumerate(v): ifval !=0: inv = pow(val,-1, MOD) v = [(x * inv) % MODforxinv] break
parsed_components.txt # 35个三次多项式y_list.txt # 35个整数(0-256)
python3 solve.py
Success at trial 8Recovered flag (utf-8): Pr0j3c7ion_4nd_M1nr4nk_4r3_p0w3rfulDone. Files written: recovered_digits.txt, recovered_flag_bytes.bin
