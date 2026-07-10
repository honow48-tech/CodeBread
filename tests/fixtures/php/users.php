<?php

require_once __DIR__ . '/db.php';

class UserRepository
{
    public function find($id)
    {
        $sql = "SELECT * FROM users WHERE id = ?";
        return db_query($sql, [$id]);
    }
}

Route::get('/users/{id}', 'UserController@show');
Route::post('/users', 'UserController@store');

function render_user_page($user)
{
    echo "Hello, " . $user['name'];
}

header('Location: dashboard.php');
