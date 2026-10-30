using System;
using System.Data;
using System.Data.OleDb;
using System.Windows.Forms;

namespace kvartira
{
    public partial class Form1 : Form
    {
        // Строка подключения к базе. 
        // ВАЖНО: файл 1.accdb должен лежать в папке bin\Debug вашего проекта!
        string connectionString = @"Provider=Microsoft.ACE.OLEDB.12.0;Data Source=1.accdb";

        public Form1()
        {
            InitializeComponent();
        }

        // Универсальная функция для загрузки данных
        private void LoadData(string sqlQuery)
        {
            try
            {
                using (OleDbConnection conn = new OleDbConnection(connectionString))
                {
                    OleDbDataAdapter adapter = new OleDbDataAdapter(sqlQuery, conn);
                    DataTable dt = new DataTable();
                    adapter.Fill(dt);

                    // Привязываем данные к таблице на форме
                    dataGridView1.DataSource = dt;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show("Ошибка подключения или запроса:\n" + ex.Message);
            }
        }

        // --- ОБРАБОТЧИКИ КНОПОК ---
        // Поскольку кнопки называются button1...button11, пишем для них методы.

        // 1. Таблица Квартиры
        private void button1_Click(object sender, EventArgs e) { LoadData("SELECT * FROM Квартиры"); }

        // 2. Таблица Риэлторы
        private void button2_Click(object sender, EventArgs e) { LoadData("SELECT * FROM Риэлторы"); }

        // 3. Таблица Сделки
        private void button3_Click(object sender, EventArgs e) { LoadData("SELECT * FROM Сделки"); }

        // 4. Таблица КВАРТИРЫ_3_КОМН
        private void button4_Click(object sender, EventArgs e) { LoadData("SELECT * FROM КВАРТИРЫ_3_КОМН"); }

        // 5. Таблица КОПИЯ_КВАРТИРЫ
        private void button5_Click(object sender, EventArgs e) { LoadData("SELECT * FROM КОПИЯ_КВАРТИРЫ"); }

        // 6-11. ЗАПРОСЫ (Замените [1], [2] и т.д. на тексты ваших запросов из Access)
        private void button6_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [1]"); }
        private void button7_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [2]"); }
        private void button8_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [3]"); }
        private void button9_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [4]"); }
        private void button10_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [5]"); }
        private void button11_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [6]"); }
        private void button12_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [7]"); }
        private void button13_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [8]"); }
        private void button14_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [9]"); }
        private void button15_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [10]"); }
        private void button16_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [11]"); }
        private void button17_Click(object sender, EventArgs e) { LoadData("SELECT * FROM [12]"); }



    }
}