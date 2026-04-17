% List utilities and arithmetic predicates

% --- List operations ---

my_length([], 0).
my_length([_|T], N) :-
    my_length(T, N1),
    N is N1 + 1.

my_append([], L, L).
my_append([H|T], L, [H|R]) :-
    my_append(T, L, R).

my_reverse([], []).
my_reverse([H|T], R) :-
    my_reverse(T, RT),
    my_append(RT, [H], R).

my_member(X, [X|_]).
my_member(X, [_|T]) :- my_member(X, T).

my_last(X, [X]).
my_last(X, [_|T]) :- my_last(X, T).

my_nth(1, [H|_], H) :- !.
my_nth(N, [_|T], X) :-
    N > 1,
    N1 is N - 1,
    my_nth(N1, T, X).

my_flatten([], []).
my_flatten([H|T], F) :-
    is_list(H), !,
    my_flatten(H, FH),
    my_flatten(T, FT),
    my_append(FH, FT, F).
my_flatten([H|T], [H|FT]) :-
    my_flatten(T, FT).

% --- Sorting ---

my_msort([], []).
my_msort([X], [X]) :- !.
my_msort(List, Sorted) :-
    length(List, Len),
    Half is Len // 2,
    length(Left, Half),
    my_append(Left, Right, List),
    my_msort(Left, SortedLeft),
    my_msort(Right, SortedRight),
    merge_sorted(SortedLeft, SortedRight, Sorted).

merge_sorted([], R, R).
merge_sorted(L, [], L).
merge_sorted([H1|T1], [H2|T2], [H1|Merged]) :-
    H1 =< H2, !,
    merge_sorted(T1, [H2|T2], Merged).
merge_sorted([H1|T1], [H2|T2], [H2|Merged]) :-
    merge_sorted([H1|T1], T2, Merged).

% --- Arithmetic ---

factorial(0, 1) :- !.
factorial(N, F) :-
    N > 0,
    N1 is N - 1,
    factorial(N1, F1),
    F is N * F1.

fibonacci(0, 0) :- !.
fibonacci(1, 1) :- !.
fibonacci(N, F) :-
    N > 1,
    N1 is N - 1,
    N2 is N - 2,
    fibonacci(N1, F1),
    fibonacci(N2, F2),
    F is F1 + F2.

gcd(X, 0, X) :- X > 0, !.
gcd(X, Y, G) :-
    Y > 0,
    R is X mod Y,
    gcd(Y, R, G).

sum_list([], 0).
sum_list([H|T], S) :-
    sum_list(T, S1),
    S is S1 + H.

max_list([X], X).
max_list([H|T], Max) :-
    max_list(T, MaxT),
    Max is max(H, MaxT).
