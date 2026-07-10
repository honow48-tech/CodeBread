using Microsoft.AspNetCore.Mvc;

namespace Demo.Controllers
{
    [ApiController]
    public class UsersController : ControllerBase
    {
        [HttpGet("/users/{id}")]
        public User GetUser(int id)
        {
            return _repository.FindById(id);
        }

        [HttpPost("/users")]
        public User CreateUser(User user)
        {
            var sql = "INSERT INTO users (name) VALUES (@name)";
            _db.Execute(sql, user);
            return user;
        }
    }
}
