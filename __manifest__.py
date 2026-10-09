{
    'name': 'Yagüven - Kardex',
    'version': '20.0.1.1.1',
    'summary': 'Reporte Kardex de inventario con saldo acumulado',
    'description': """
Reporte Kardex accesible desde Inventario -> Reportes -> Kardex: saldo inicial + movimientos
+ saldo acumulado (running balance) por producto/ubicación en un rango de fechas, con
exportación a Excel. Ubicaciones con hijos: excluye automáticamente los movimientos internos
entre ellas.

Port de guvens_kardex (Odoo 17) a Odoo 19: vistas tree -> list, y filtro de producto por
categoría adaptado de type='product' a is_storable=True (el tipo 'Storable Product' se
eliminó en 19).

Historia de Odoo 17 (20.0.1.1.0): yaguven.kardex.historia guarda los movimientos de O17 como
dato de consulta; antes de la fecha de corte el Kardex lee la historia y después los
movimientos de la 20, sin los de la carga inicial. La carga la hace un script del proyecto.
""",
    'author': 'Yagüven C.G.',
    'category': 'Inventory',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'security/ir.access.csv',
        'views/kardex_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
